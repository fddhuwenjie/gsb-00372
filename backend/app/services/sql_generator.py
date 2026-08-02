from copy import deepcopy

from app.services.security_service import SecurityService
from app.services.utils import (
    detect_circular_dependency,
    sort_ctes_by_dependency,
    validate_cte_names,
)


class SQLGenerator:
    """
    Compiles a JSON query AST into a single parameterised read-only SQL
    statement plus a dict of named parameters.

    The AST is the *only* contract between the React frontend and the backend.
    The frontend never builds SQL strings; it sends this structure and the
    backend is the sole source of truth for SQL semantics.

    Every table instance has a stable ``id`` and a unique ``alias``. All
    column references are bound to a table instance via ``tableId`` so that
    self-joins, duplicate column names and JOIN reordering can never be
    ambiguous.
    """

    def __init__(self, query_structure, param_values=None):
        self.query_structure = deepcopy(query_structure)
        self.params = {}
        self.param_counter = 0
        # Externally supplied values for declared template parameters.
        # Maps declared parameter name -> value. These are emitted as
        # eponymous named bind variables (e.g. :country_filter) so the
        # generated SQL/params stay cleanly separated.
        self.param_values = param_values or {}
        self._used_param_names = set()
        SecurityService.validate_ast_structure(self.query_structure)
        self._tables_by_id = {
            t['id']: t for t in self.query_structure.get('tables', [])
        }
        self.ctes = self.query_structure.get('ctes') or []
        if self.ctes:
            validate_cte_names(self.ctes)
            if detect_circular_dependency(self.ctes):
                raise ValueError('Circular dependency detected in CTEs')
            self.ctes = sort_ctes_by_dependency(self.ctes)

    # ------------------------------------------------------------------
    # Parameter helpers
    # ------------------------------------------------------------------
    def _next_param(self, value):
        self.param_counter += 1
        name = f'p{self.param_counter}'
        self.params[name] = value
        return f':{name}'

    def _bind_named_param(self, name):
        """Bind a declared template parameter by its declared name."""
        SecurityService.validate_identifier(name)
        if name not in self.param_values:
            raise ValueError(f'Missing value for template parameter: {name}')
        value = self.param_values[name]
        # Use the declared name directly in the SQL text; SQLAlchemy named
        # bind variables accept any valid identifier.
        self.params[name] = value
        self._used_param_names.add(name)
        return f':{name}'

    def _resolve_value(self, node):
        """
        Return (value, is_inline) for a condition leaf. If the node references
        a declared parameter via ``param``, the value is pulled from the
        supplied parameter map. Inline ``value`` keys are returned as-is.
        """
        if 'param' in node and node['param'] is not None:
            name = node['param']
            if name not in self.param_values:
                raise ValueError(f'Missing value for template parameter: {name}')
            return self.param_values[name], name
        return node.get('value'), None

    def _bind_value(self, node):
        """Resolve a node's value/param and return a bind placeholder."""
        value, param_name = self._resolve_value(node)
        if param_name is not None:
            return self._bind_named_param(param_name)
        return self._next_param(
            SecurityService.validate_scalar_value(value)
        )

    def _merge_params(self, other_params):
        """Merge params from a sub-generator, renaming to avoid collisions."""
        offset = self.param_counter
        mapping = {}
        for key, value in other_params.items():
            new_key = f'p{int(key[1:]) + offset}'
            mapping[f':{key}'] = f':{new_key}'
            self.params[new_key] = value
            self.param_counter += 1
        return mapping

    def _sub_generator(self, sub_ast):
        """Create a child SQLGenerator sharing the same template param values."""
        return SQLGenerator(sub_ast, param_values=self.param_values)

    # ------------------------------------------------------------------
    # Identifier resolution
    # ------------------------------------------------------------------
    def _get_table(self, table_id):
        table = self._tables_by_id.get(table_id)
        if not table:
            raise ValueError(f'Unknown table instance: {table_id}')
        return table

    def _alias_for(self, table_id):
        table = self._get_table(table_id)
        return table.get('alias') or table['id']

    def _qualified_column(self, table_id, column_name):
        alias = SecurityService.validate_identifier(self._alias_for(table_id))
        col = SecurityService.validate_column_name(column_name)
        return (
            f'{SecurityService.quote_identifier(alias)}.'
            f'{SecurityService.quote_identifier(col)}'
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def generate(self):
        sql = self._generate_select_statement(self.query_structure)
        SecurityService.audit_sql_text(sql)
        return sql

    def get_params(self):
        return dict(self.params)

    # ------------------------------------------------------------------
    # SELECT assembly
    # ------------------------------------------------------------------
    def _generate_select_statement(self, qs):
        parts = []
        cte_sql = self._generate_ctes(qs)
        if cte_sql:
            parts.append(cte_sql)
        parts.append(self._generate_select(qs))
        parts.append(self._generate_from_and_joins(qs))
        where = self._generate_condition(qs.get('where'))
        if where:
            parts.append(f'WHERE {where}')
        group_by = self._generate_group_by(qs)
        if group_by:
            parts.append(group_by)
        having = self._generate_condition(qs.get('having'))
        if having:
            parts.append(f'HAVING {having}')
        order_by = self._generate_order_by(qs)
        if order_by:
            parts.append(order_by)
        parts.append(self._generate_pagination(qs))
        return '\n'.join(parts)

    def _generate_ctes(self, qs):
        ctes = qs.get('ctes') or []
        if not ctes:
            return None
        cte_parts = []
        for cte in ctes:
            name = SecurityService.validate_identifier(cte['name'])
            sub_gen = self._sub_generator(cte['queryStructure'])
            sub_sql = sub_gen._generate_select_statement(cte['queryStructure'])
            # Template-named params (e.g. :country) share the same namespace
            # across parent and subquery; only auto-generated pN placeholders
            # need collision renaming.
            auto_params = {
                k: v for k, v in sub_gen.params.items()
                if k not in self.param_values
            }
            param_map = self._merge_params(auto_params)
            for old, new in param_map.items():
                sub_sql = sub_sql.replace(old, new)
            cte_parts.append(
                f'{SecurityService.quote_identifier(name)} AS (\n{sub_sql}\n)'
            )
        return 'WITH ' + ',\n'.join(cte_parts)

    def _generate_select(self, qs):
        selected = qs.get('selectedFields') or []
        aggregations = qs.get('aggregations') or []
        agg_keys = {
            (a['tableId'], a['columnName']) for a in aggregations
        }

        items = []
        for field in selected:
            if (field['tableId'], field['columnName']) in agg_keys:
                continue
            col = self._qualified_column(field['tableId'], field['columnName'])
            alias = field.get('alias')
            if alias:
                items.append(
                    f'{col} AS {SecurityService.quote_identifier(alias)}'
                )
            else:
                items.append(col)

        for agg in aggregations:
            func = SecurityService.validate_aggregation(agg['function'])
            if agg['columnName'] == '*':
                col = '*'
            else:
                col = self._qualified_column(agg['tableId'], agg['columnName'])
            alias = agg.get('alias') or f'{func.lower()}_{agg["columnName"]}'
            SecurityService.validate_alias(alias)
            items.append(
                f'{func}({col}) AS {SecurityService.quote_identifier(alias)}'
            )

        if not items:
            items = ['*']
        return f'SELECT {", ".join(items)}'

    # ------------------------------------------------------------------
    # FROM / JOIN
    # ------------------------------------------------------------------
    def _generate_from_and_joins(self, qs):
        tables = qs.get('tables') or []
        joins = qs.get('joins') or []
        if not tables:
            raise ValueError('No tables selected')

        if not joins:
            first = tables[0]
            return self._from_clause(first)

        ordered_tables, ordered_joins = self._order_joins(tables, joins)
        first = ordered_tables[0]
        lines = [self._from_clause(first)]
        for join in ordered_joins:
            lines.append(self._render_join(join))
        return '\n'.join(lines)

    def _from_clause(self, table):
        name = SecurityService.validate_table_name(table['tableName'])
        alias = SecurityService.validate_identifier(
            table.get('alias') or table['id']
        )
        return (
            f'FROM {SecurityService.quote_identifier(name)} '
            f'{SecurityService.quote_identifier(alias)}'
        )

    def _order_joins(self, tables, joins):
        """
        Produce a linear ordering of tables and joins. We honour the order
        in the AST (which reflects the order the user connected nodes) so
        that the resulting SQL is stable and predictable. The graph must be
        connected; disconnected tables raise an error.
        """
        table_ids = [t['id'] for t in tables]
        if len(table_ids) == 1:
            return tables, []

        adjacency = {tid: [] for tid in table_ids}
        join_by_id = {}
        for join in joins:
            join_by_id[join['id']] = join
            adjacency[join['leftTableId']].append(
                (join['rightTableId'], join, False)
            )
            adjacency[join['rightTableId']].append(
                (join['leftTableId'], join, True)
            )

        ordered_ids = [table_ids[0]]
        visited = {table_ids[0]}
        ordered_joins = []

        while len(ordered_ids) < len(table_ids):
            progressed = False
            for tid in list(ordered_ids):
                for neighbour, join, reversed_ in adjacency[tid]:
                    if neighbour in visited:
                        continue
                    visited.add(neighbour)
                    ordered_ids.append(neighbour)
                    if reversed_:
                        ordered_joins.append(self._reverse_join(join))
                    else:
                        ordered_joins.append(join)
                    progressed = True
            if not progressed:
                raise ValueError(
                    'All tables must be connected by JOINs'
                )

        ordered_tables = [
            next(t for t in tables if t['id'] == tid) for tid in ordered_ids
        ]
        return ordered_tables, ordered_joins

    @staticmethod
    def _reverse_join(join):
        return {
            **join,
            'leftTableId': join['rightTableId'],
            'leftColumn': join['rightColumn'],
            'leftTable': join['rightTable'],
            'rightTableId': join['leftTableId'],
            'rightColumn': join['leftColumn'],
            'rightTable': join['leftTable'],
        }

    def _render_join(self, join):
        join_type = SecurityService.validate_join_type(join['type'])
        right_name = SecurityService.validate_table_name(join['rightTable'])
        right_alias = SecurityService.validate_identifier(
            self._alias_for(join['rightTableId'])
        )
        table_sql = (
            f'{SecurityService.quote_identifier(right_name)} '
            f'{SecurityService.quote_identifier(right_alias)}'
        )
        if join_type == 'CROSS':
            return f'CROSS JOIN {table_sql}'
        left_col = self._qualified_column(
            join['leftTableId'], join['leftColumn']
        )
        right_col = self._qualified_column(
            join['rightTableId'], join['rightColumn']
        )
        return (
            f'{join_type} JOIN {table_sql} ON {left_col} = {right_col}'
        )

    # ------------------------------------------------------------------
    # WHERE / HAVING condition tree (supports AND/OR/NOT)
    # ------------------------------------------------------------------
    def _generate_condition(self, node):
        if node is None:
            return None

        if not isinstance(node, dict):
            raise ValueError('Condition node must be an object')

        if 'op' in node:
            op = node['op'].upper()
            if op in ('AND', 'OR'):
                parts = []
                for child in node.get('children', []):
                    child_sql = self._generate_condition(child)
                    if child_sql:
                        parts.append(child_sql)
                if not parts:
                    return None
                if len(parts) == 1:
                    return parts[0]
                return f'({f" {op} ".join(parts)})'
            if op == 'NOT':
                child_sql = self._generate_condition(node.get('child'))
                if not child_sql:
                    return None
                return f'NOT ({child_sql})'
            raise ValueError(f'Unsupported logical operator: {op}')

        cmp = SecurityService.validate_operator(node['cmp'])
        return self._render_predicate(node, cmp)

    def _render_predicate(self, node, cmp):
        if cmp in ('EXISTS', 'NOT EXISTS'):
            sub_sql = self._render_subquery(node['subquery'])
            return f'{cmp} (\n{sub_sql}\n)'

        if node.get('function'):
            func = SecurityService.validate_aggregation(node['function'])
            if node.get('columnName') == '*':
                col = '*'
            else:
                col = self._qualified_column(node['tableId'], node['columnName'])
            col = f'{func}({col})'
        else:
            col = self._qualified_column(node['tableId'], node['columnName'])

        if cmp in ('IS NULL', 'IS NOT NULL'):
            return f'{col} {cmp}'

        if cmp in ('IN', 'NOT IN'):
            if node.get('subquery') is not None:
                sub_sql = self._render_subquery(node['subquery'])
                return f'{col} {cmp} (\n{sub_sql}\n)'
            value, param_name = self._resolve_value(node)
            values = SecurityService.validate_in_value(value)
            if not values:
                # SQL standard / SQLite: empty IN is FALSE, empty NOT IN is
                # TRUE. We express these as constants so no SQL is generated
                # with an empty value list.
                return '0 = 1' if cmp == 'IN' else '1 = 1'
            if param_name is not None:
                # An IN list bound to a template parameter is a single JSON
                # list value. We expand it into per-element named parameters
                # so the SQL structure is still fixed and no list is
                # interpolated as text.
                placeholders = [
                    self._bind_in_element(param_name, idx, v)
                    for idx, v in enumerate(values)
                ]
            else:
                placeholders = [self._next_param(v) for v in values]
            return f'{col} {cmp} ({", ".join(placeholders)})'

        if cmp in ('LIKE', 'NOT LIKE'):
            return f'{col} {cmp} {self._bind_value(node)}'

        value, _ = self._resolve_value(node)
        if value is None:
            # Normalise equality with NULL to IS NULL / IS NOT NULL so the
            # predicate behaves as users expect.
            if cmp == '=':
                return f'{col} IS NULL'
            if cmp in ('!=', '<>'):
                return f'{col} IS NOT NULL'
        return f'{col} {cmp} {self._bind_value(node)}'

    def _bind_in_element(self, base_name, index, value):
        """Bind one element of an IN list that references a template param."""
        self.param_counter += 1
        placeholder = f'{base_name}_{index}'
        # Avoid clashing with auto pN names.
        self.params[placeholder] = value
        return f':{placeholder}'

    def _render_subquery(self, sub_ast):
        sub_gen = self._sub_generator(sub_ast)
        sub_sql = sub_gen._generate_select_statement(sub_ast)
        auto_params = {
            k: v for k, v in sub_gen.params.items()
            if k not in self.param_values
        }
        param_map = self._merge_params(auto_params)
        for old, new in param_map.items():
            sub_sql = sub_sql.replace(old, new)
        return sub_sql

    # ------------------------------------------------------------------
    # GROUP BY / ORDER BY / pagination
    # ------------------------------------------------------------------
    def _generate_group_by(self, qs):
        aggregations = qs.get('aggregations') or []
        if not aggregations:
            return None
        agg_keys = {
            (a['tableId'], a['columnName']) for a in aggregations
        }
        group_cols = []
        for field in qs.get('selectedFields') or []:
            if (field['tableId'], field['columnName']) not in agg_keys:
                group_cols.append(
                    self._qualified_column(
                        field['tableId'], field['columnName']
                    )
                )
        if not group_cols:
            return None
        return f'GROUP BY {", ".join(group_cols)}'

    def _generate_order_by(self, qs):
        orders = qs.get('orderBy') or []
        if not orders:
            return None
        parts = []
        for order in orders:
            col = self._qualified_column(order['tableId'], order['columnName'])
            direction = (order.get('direction') or 'ASC').upper()
            if direction not in ('ASC', 'DESC'):
                raise ValueError(f'Invalid ORDER BY direction: {direction}')
            parts.append(f'{col} {direction}')
        return f'ORDER BY {", ".join(parts)}'

    def _generate_pagination(self, qs):
        # LIMIT / OFFSET may be either inline integers or references to
        # declared template parameters. In both cases the values are bound
        # as parameters; they are never interpolated into the SQL text.
        limit_val, limit_param = self._resolve_pagination_value(qs, 'limit')
        offset_val, offset_param = self._resolve_pagination_value(qs, 'offset')

        if limit_param is not None:
            SecurityService.validate_limit(limit_val)
            limit_placeholder = self._bind_named_param(limit_param)
        else:
            limit_val = SecurityService.validate_limit(limit_val)
            limit_placeholder = self._next_param(limit_val)

        if offset_val:
            SecurityService.validate_offset(offset_val)
            if offset_param is not None:
                offset_placeholder = self._bind_named_param(offset_param)
            else:
                offset_placeholder = self._next_param(offset_val)
            return f'LIMIT {limit_placeholder} OFFSET {offset_placeholder}'
        return f'LIMIT {limit_placeholder}'

    def _resolve_pagination_value(self, qs, key):
        """Resolve a pagination value that may be inline or a param ref.

        The AST uses ``limitParam`` / ``offsetParam`` keys (string) to
        reference a declared template parameter. If those keys are present
        they take precedence over the inline ``limit`` / ``offset`` keys.
        """
        param_key = f'{key}Param'
        if qs.get(param_key):
            name = qs[param_key]
            if name not in self.param_values:
                raise ValueError(f'Missing value for template parameter: {name}')
            return self.param_values[name], name
        return qs.get(key), None
