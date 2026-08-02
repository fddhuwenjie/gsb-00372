from app.services.security_service import SecurityService
from app.services.utils import sort_ctes_by_dependency, validate_cte_names, detect_circular_dependency
from copy import deepcopy


class _ParamContext:
    """Shared parameter accumulator so nested generators (CTEs, subqueries)
    never collide on parameter names. Every value the user supplies -- and the
    pagination bounds -- flows through here, keeping SQL text and the parameter
    list strictly separated."""

    def __init__(self):
        self.counter = 0
        self.params = {}

    def add(self, value):
        self.counter += 1
        name = f'p{self.counter}'
        self.params[name] = value
        return f':{name}'


class SQLGenerator:
    def __init__(self, query_structure, param_ctx=None):
        self.query_structure = deepcopy(query_structure)
        self.param_ctx = param_ctx if param_ctx is not None else _ParamContext()
        self._tables_by_id = {t['id']: t for t in self.query_structure.get('tables', [])}
        self.ctes = self.query_structure.get('ctes') or []
        if self.ctes:
            validate_cte_names(self.ctes)
            if detect_circular_dependency(self.ctes):
                raise ValueError('Circular dependency detected in CTEs')
            self.ctes = sort_ctes_by_dependency(self.ctes)

    # ----- parameters -----
    def _next_param(self, value):
        return self.param_ctx.add(value)

    def get_params(self):
        return self.param_ctx.params

    # ----- table / column resolution (bound to table instance id) -----
    def _get_table_alias(self, table_id):
        table = self._tables_by_id.get(table_id)
        if not table:
            raise ValueError(f'Table instance not found: {table_id}')
        return SecurityService.validate_identifier(table['alias'])

    def _get_qualified_column(self, table_id, column_name):
        alias = self._get_table_alias(table_id)
        col = SecurityService.validate_column_name(column_name)
        return f'{SecurityService.quote_identifier(alias)}.{SecurityService.quote_identifier(col)}'

    # ----- entry point -----
    def generate(self):
        # Reject unsupported physical joins up-front so callers get a clear error.
        for join in self.query_structure.get('joins', []):
            SecurityService.validate_join_type(join.get('type'))
        return self._generate_normal()

    def _generate_normal(self):
        sql_parts = []

        cte_clause = self._generate_ctes()
        if cte_clause:
            sql_parts.append(cte_clause)

        sql_parts.append(self._generate_select())
        sql_parts.append(self._generate_from_and_joins())

        where_clause = self._generate_where()
        if where_clause:
            sql_parts.append(where_clause)

        group_by_clause = self._generate_group_by()
        if group_by_clause:
            sql_parts.append(group_by_clause)

        having_clause = self._generate_having()
        if having_clause:
            sql_parts.append(having_clause)

        order_by_clause = self._generate_order_by()
        if order_by_clause:
            sql_parts.append(order_by_clause)

        sql_parts.append(self._generate_limit_offset())

        return '\n'.join(sql_parts)

    # ----- SELECT -----
    def _is_aggregated(self, field, aggregations):
        return any(
            agg['tableId'] == field['tableId'] and agg['columnName'] == field['columnName']
            for agg in aggregations
        )

    def _generate_select(self):
        selected_fields = self.query_structure.get('selectedFields', [])
        aggregations = self.query_structure.get('aggregations', [])

        select_items = []

        for field in selected_fields:
            if self._is_aggregated(field, aggregations):
                continue
            col = self._get_qualified_column(field['tableId'], field['columnName'])
            alias = SecurityService.validate_alias(field.get('alias'))
            if alias:
                select_items.append(f'{col} AS {SecurityService.quote_identifier(alias)}')
            else:
                select_items.append(col)

        for agg in aggregations:
            func = SecurityService.validate_aggregation(agg['function'])
            col = self._get_qualified_column(agg['tableId'], agg['columnName'])
            alias = SecurityService.validate_alias(agg.get('alias'))
            if not alias:
                alias = f"{func.lower()}_{SecurityService.validate_column_name(agg['columnName'])}"
            select_items.append(f'{func}({col}) AS {SecurityService.quote_identifier(alias)}')

        if not select_items:
            select_items = ['*']

        return f'SELECT {", ".join(select_items)}'

    # ----- FROM / JOIN -----
    def _generate_from_and_joins(self):
        tables = self.query_structure.get('tables', [])
        joins = self.query_structure.get('joins', [])

        if not tables:
            raise ValueError('No tables selected')

        anchor = self._choose_anchor(tables, joins)
        from_clause = f'FROM {self._table_ref(anchor)}'
        if not joins:
            return from_clause

        join_sql = self._order_joins(tables, joins, anchor)
        return '\n'.join([from_clause] + join_sql)

    def _choose_anchor(self, tables, joins):
        """Pick the FROM anchor. A table that is the optional (right) side of a
        LEFT join must not anchor the query, otherwise its preserving table
        could not be attached without RIGHT-join semantics. This keeps results
        stable regardless of the order tables were added to the AST."""
        optional_sides = {
            j['rightTableId'] for j in joins if j.get('type') == 'LEFT'
        }
        for table in tables:
            if table['id'] not in optional_sides:
                return table
        # All tables are optional sides (only possible with cycles); fall back.
        return tables[0]

    def _table_ref(self, table):
        name = SecurityService.validate_table_name(table['tableName'])
        alias = SecurityService.validate_identifier(table['alias'])
        return f'{SecurityService.quote_identifier(name)} {SecurityService.quote_identifier(alias)}'

    def _order_joins(self, tables, joins, anchor):
        """Emit joins so every join attaches a not-yet-in-scope table to the
        already-in-scope query. This makes the generated SQL deterministic and
        valid regardless of the order joins were authored in. LEFT joins keep
        their directionality (the left/preserved side must already be in scope)."""
        in_scope = {anchor['id']}
        remaining = list(joins)
        ordered = []

        while remaining:
            progressed = False
            for join in list(remaining):
                left_id = join['leftTableId']
                right_id = join['rightTableId']
                jtype = join.get('type')

                left_in = left_id in in_scope
                right_in = right_id in in_scope

                if left_in and right_in:
                    # Both already joined: this is an extra ON predicate.
                    ordered.append(('extra', join))
                    remaining.remove(join)
                    progressed = True
                elif left_in and not right_in:
                    ordered.append(('attach', join, right_id))
                    in_scope.add(right_id)
                    remaining.remove(join)
                    progressed = True
                elif right_in and not left_in:
                    # The new table sits on the left side of the join spec.
                    if jtype == 'LEFT':
                        # Would require RIGHT-join semantics to preserve meaning.
                        raise ValueError(
                            'LEFT JOIN ordering would require RIGHT JOIN semantics; '
                            'reorder tables so the preserved table comes first'
                        )
                    ordered.append(('attach', join, left_id))
                    in_scope.add(left_id)
                    remaining.remove(join)
                    progressed = True
            if not progressed:
                raise ValueError('Disconnected join graph: some tables are not joined')

        parts = []
        for entry in ordered:
            if entry[0] == 'attach':
                parts.append(self._render_join(entry[1], entry[2]))
            else:
                # Extra predicate on an already-joined pair: fold into last join
                # is complex; instead reject as ambiguous to keep semantics clear.
                raise ValueError('Redundant join between already-joined tables')
        return [p for p in parts]

    def _render_join(self, join, new_table_id):
        return self._generate_single_join_for(join, new_table_id)

    def _generate_single_join(self, join):  # retained for compatibility
        return self._generate_single_join_for(join, join['rightTableId'])

    def _generate_single_join_for(self, join, new_table_id):
        join_type = SecurityService.validate_join_type(join['type'])
        new_table = self._tables_by_id.get(new_table_id)
        if not new_table:
            raise ValueError(f'Table instance not found: {new_table_id}')
        table_ref = self._table_ref(new_table)

        if join_type == 'CROSS':
            return f'CROSS JOIN {table_ref}'

        left_col = self._get_qualified_column(join['leftTableId'], join['leftColumn'])
        right_col = self._get_qualified_column(join['rightTableId'], join['rightColumn'])
        return f'{join_type} JOIN {table_ref} ON {left_col} = {right_col}'

    # ----- WHERE / HAVING condition trees -----
    def _generate_where(self):
        where = self.query_structure.get('where')
        if not where:
            return None
        sql = self._generate_condition_tree(where, aggregate_context=False)
        return f'WHERE {sql}' if sql else None

    def _generate_having(self):
        having = self.query_structure.get('having')
        if not having:
            return None
        sql = self._generate_condition_tree(having, aggregate_context=True)
        return f'HAVING {sql}' if sql else None

    def _generate_condition_tree(self, node, aggregate_context):
        op = node.get('op')
        if op in ('AND', 'OR', 'NOT') and 'children' in node:
            SecurityService.validate_logical(op)
            children_sql = []
            for child in node['children']:
                child_sql = self._generate_condition_tree(child, aggregate_context)
                if child_sql:
                    children_sql.append(child_sql)
            if not children_sql:
                return None
            if op == 'NOT':
                if len(children_sql) == 1:
                    return f'(NOT {children_sql[0]})'
                combined = ' AND '.join(children_sql)
                return f'(NOT ({combined}))'
            if len(children_sql) == 1:
                return children_sql[0]
            return f'({f" {op} ".join(children_sql)})'

        if 'cmp' in node:
            return self._generate_leaf(node, aggregate_context)

        return None

    def _leaf_column_expr(self, node, aggregate_context):
        col = self._get_qualified_column(node['tableId'], node['columnName'])
        func = node.get('function')
        if func:
            func = SecurityService.validate_aggregation(func)
            return f'{func}({col})'
        return col

    def _generate_leaf(self, node, aggregate_context):
        cmp = SecurityService.validate_operator(node['cmp'])

        if cmp in ('EXISTS', 'NOT EXISTS'):
            return self._generate_subquery_condition(node, cmp)

        col = self._leaf_column_expr(node, aggregate_context)

        if cmp in ('IS NULL', 'IS NOT NULL'):
            return f'{col} {cmp}'

        if cmp in ('IN', 'NOT IN'):
            if 'subquery' in node and node.get('subquery'):
                return self._generate_subquery_condition(node, cmp, col)
            value = node.get('value')
            if not isinstance(value, list):
                raise ValueError(f'{cmp} operator requires a list value')
            if len(value) == 0:
                # Empty IN is always false; empty NOT IN is always true.
                return '(1 = 0)' if cmp == 'IN' else '(1 = 1)'
            placeholders = [self._next_param(v) for v in value]
            return f'{col} {cmp} ({", ".join(placeholders)})'

        # Scalar comparison / LIKE
        value = SecurityService.validate_value(node.get('value'))
        param = self._next_param(value)
        return f'{col} {cmp} {param}'

    def _generate_subquery_condition(self, node, cmp, col=None):
        subquery_structure = node.get('subquery')
        if not subquery_structure:
            raise ValueError('Subquery structure required for subquery condition')
        sub_gen = SQLGenerator(subquery_structure, param_ctx=self.param_ctx)
        sub_sql = sub_gen._generate_normal()

        if cmp in ('EXISTS', 'NOT EXISTS'):
            return f'{cmp} (\n{sub_sql}\n)'
        if col is None:
            col = self._leaf_column_expr(node, aggregate_context=False)
        return f'{col} {cmp} (\n{sub_sql}\n)'

    # ----- GROUP BY -----
    def _generate_group_by(self):
        aggregations = self.query_structure.get('aggregations', [])
        if not aggregations:
            return None
        selected_fields = self.query_structure.get('selectedFields', [])
        group_by_fields = []
        for field in selected_fields:
            if not self._is_aggregated(field, aggregations):
                group_by_fields.append(
                    self._get_qualified_column(field['tableId'], field['columnName'])
                )
        if group_by_fields:
            return f'GROUP BY {", ".join(group_by_fields)}'
        return None

    # ----- ORDER BY -----
    def _generate_order_by(self):
        order_by = self.query_structure.get('orderBy') or []
        if not order_by:
            return None
        items = []
        aggregations = self.query_structure.get('aggregations', [])
        for spec in order_by:
            direction = SecurityService.validate_sort_direction(spec.get('direction'))
            func = spec.get('function')
            if func:
                func = SecurityService.validate_aggregation(func)
                col = self._get_qualified_column(spec['tableId'], spec['columnName'])
                items.append(f'{func}({col}) {direction}')
            else:
                col = self._get_qualified_column(spec['tableId'], spec['columnName'])
                items.append(f'{col} {direction}')
        if not items:
            return None
        return f'ORDER BY {", ".join(items)}'

    # ----- LIMIT / OFFSET (bound parameters) -----
    def _generate_limit_offset(self):
        limit = SecurityService.validate_limit(self.query_structure.get('limit', 100))
        offset = SecurityService.validate_offset(self.query_structure.get('offset', 0))
        limit_param = self._next_param(limit)
        if offset:
            offset_param = self._next_param(offset)
            return f'LIMIT {limit_param} OFFSET {offset_param}'
        return f'LIMIT {limit_param}'

    # ----- CTEs -----
    def _generate_ctes(self):
        if not self.ctes:
            return None
        cte_parts = []
        for cte in self.ctes:
            cte_name = SecurityService.validate_identifier(cte['name'])
            sub_gen = SQLGenerator(cte['queryStructure'], param_ctx=self.param_ctx)
            sub_sql = sub_gen._generate_normal()
            cte_parts.append(f'{SecurityService.quote_identifier(cte_name)} AS (\n{sub_sql}\n)')
        return 'WITH ' + ',\n'.join(cte_parts)
