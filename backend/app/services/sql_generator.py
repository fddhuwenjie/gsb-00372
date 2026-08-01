from app.services.security_service import SecurityService
from app.services.utils import sort_ctes_by_dependency, validate_cte_names, detect_circular_dependency
from copy import deepcopy


class ParamAllocator:
    """Allocates unique named bind parameters for a whole query (including
    nested CTEs and subqueries) so SQL text and values stay separated."""

    def __init__(self):
        self.params = {}
        self.counter = 0

    def bind(self, value):
        self.counter += 1
        name = f'p{self.counter}'
        self.params[name] = value
        return f':{name}'


class SQLGenerator:
    """Generates a single read-only, fully parameterized SELECT statement
    from a query AST. This class is the single source of truth for SQL
    semantics; the frontend only manipulates the AST.

    Unified AST fields (QueryStructure):
      tables:         [{id, tableName, alias, position?}]  - stable per-instance id+alias
      joins:          [{id, type, leftTableId, leftColumn, rightTableId, rightColumn,
                        leftTable, rightTable}]            - type in INNER/LEFT/CROSS
      selectedFields: [{tableId, columnName, alias?}]      - bound to a table instance id
      where:          condition tree | None
      having:         condition tree | None
      aggregations:   [{tableId, columnName, function, alias?}]
      limit:          int (1..1000, bound parameter)
      offset:         int (>=0, bound parameter)
      ctes:           [{id, name, queryStructure}]

    Condition tree nodes:
      group:  {id, op: AND|OR, children: [node, ...]}
      not:    {id, op: NOT, children: [node]}
      clause: {id, tableId, columnName, cmp, value?, function?, subquery?}
              cmp in =, !=, >, <, >=, <=, LIKE, IN, NOT IN,
                     IS NULL, IS NOT NULL, EXISTS, NOT EXISTS
    """

    def __init__(self, query_structure, allocator=None):
        self.query_structure = deepcopy(query_structure)
        self.allocator = allocator or ParamAllocator()
        self._validate_structure()
        self._tables_by_id = {t['id']: t for t in self.query_structure.get('tables', [])}
        self.ctes = self.query_structure.get('ctes', []) or []
        if self.ctes:
            validate_cte_names(self.ctes)
            if detect_circular_dependency(self.ctes):
                raise ValueError('Circular dependency detected in CTEs')
            self.ctes = sort_ctes_by_dependency(self.ctes)

    # ------------------------------------------------------------------
    # AST validation
    # ------------------------------------------------------------------
    def _validate_structure(self):
        tables = self.query_structure.get('tables', []) or []
        if not tables:
            raise ValueError('No tables selected')

        seen_ids = set()
        used_aliases = set()
        for index, table in enumerate(tables):
            table_id = table.get('id')
            if not table_id:
                raise ValueError('Every table instance requires a stable id')
            if table_id in seen_ids:
                raise ValueError(f'Duplicate table instance id: {table_id}')
            seen_ids.add(table_id)

            SecurityService.validate_table_name(table.get('tableName'))

            alias = table.get('alias')
            if not alias:
                # Derive a stable, deterministic alias from the table name so
                # repeated instances (self-joins) stay unambiguous.
                base = table['tableName']
                alias = base
                n = 2
                while alias in used_aliases:
                    alias = f'{base}_{n}'
                    n += 1
                table['alias'] = alias
            SecurityService.validate_identifier(alias)
            if alias in used_aliases:
                raise ValueError(f'Duplicate table alias: {alias}')
            used_aliases.add(alias)

        for join in self.query_structure.get('joins', []) or []:
            left_id = join.get('leftTableId')
            right_id = join.get('rightTableId')
            if left_id not in seen_ids:
                raise ValueError(f'Join references unknown table instance: {left_id}')
            if right_id not in seen_ids:
                raise ValueError(f'Join references unknown table instance: {right_id}')
            if left_id == right_id:
                raise ValueError('A join must connect two distinct table instances')
            # Rejects RIGHT/FULL explicitly (SQLite does not support them).
            SecurityService.validate_join_type(join.get('type'))
            if join.get('type') != 'CROSS':
                SecurityService.validate_column_name(join.get('leftColumn'))
                SecurityService.validate_column_name(join.get('rightColumn'))

        for field in self.query_structure.get('selectedFields', []) or []:
            if field.get('tableId') not in seen_ids:
                raise ValueError(f"Selected field references unknown table instance: {field.get('tableId')}")
            SecurityService.validate_column_name(field.get('columnName'))
            SecurityService.validate_alias(field.get('alias'))

        for agg in self.query_structure.get('aggregations', []) or []:
            if agg.get('tableId') not in seen_ids:
                raise ValueError(f"Aggregation references unknown table instance: {agg.get('tableId')}")
            SecurityService.validate_column_name(agg.get('columnName'))
            SecurityService.validate_aggregation(agg.get('function'))
            SecurityService.validate_alias(agg.get('alias'))

        SecurityService.validate_limit(self.query_structure.get('limit', 100))
        SecurityService.validate_offset(self.query_structure.get('offset', 0))

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def generate(self):
        sql_parts = []

        cte_clause = self._generate_ctes()
        if cte_clause:
            sql_parts.append(cte_clause)

        sql_parts.append(self._generate_select())
        sql_parts.append(self._generate_from_and_joins())

        where_clause = self._generate_condition_section('WHERE', self.query_structure.get('where'))
        if where_clause:
            sql_parts.append(where_clause)

        group_by_clause = self._generate_group_by()
        if group_by_clause:
            sql_parts.append(group_by_clause)

        having_clause = self._generate_condition_section('HAVING', self.query_structure.get('having'))
        if having_clause:
            sql_parts.append(having_clause)

        # Pagination values are bound parameters, never inlined.
        limit = SecurityService.validate_limit(self.query_structure.get('limit', 100))
        sql_parts.append(f'LIMIT {self.allocator.bind(limit)}')

        offset = SecurityService.validate_offset(self.query_structure.get('offset', 0))
        if offset:
            sql_parts.append(f'OFFSET {self.allocator.bind(offset)}')

        sql = '\n'.join(sql_parts)
        SecurityService.validate_read_only_sql(sql)
        return sql

    def get_params(self):
        return self.allocator.params

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------
    def _get_table_alias(self, table_id):
        table = self._tables_by_id.get(table_id)
        if table:
            return table['alias']
        raise ValueError(f'Table not found: {table_id}')

    def _get_qualified_column(self, table_id, column_name):
        alias = self._get_table_alias(table_id)
        col = SecurityService.validate_column_name(column_name)
        return f'{SecurityService.quote_identifier(alias)}.{SecurityService.quote_identifier(col)}'

    def _generate_select(self):
        selected_fields = self.query_structure.get('selectedFields', []) or []
        aggregations = self.query_structure.get('aggregations', []) or []

        # Each item: (sql_expression, output_name, has_explicit_alias)
        items = []

        for field in selected_fields:
            is_aggregated = any(
                agg['tableId'] == field['tableId'] and agg['columnName'] == field['columnName']
                for agg in aggregations
            )
            if is_aggregated:
                continue
            col = self._get_qualified_column(field['tableId'], field['columnName'])
            explicit = field.get('alias')
            items.append({
                'expr': col,
                'name': explicit or field['columnName'],
                'explicit': bool(explicit),
                'always_alias': False,
                'qualifier': f"{self._get_table_alias(field['tableId'])}_{field['columnName']}",
            })

        for agg in aggregations:
            func = SecurityService.validate_aggregation(agg['function'])
            col = self._get_qualified_column(agg['tableId'], agg['columnName'])
            expr = f'{func}({col})'
            explicit = agg.get('alias')
            items.append({
                'expr': expr,
                'name': explicit or f"{func.lower()}_{agg['columnName']}",
                'explicit': bool(explicit),
                # aggregated expressions always get an output alias
                'always_alias': True,
                'qualifier': f"{self._get_table_alias(agg['tableId'])}_{func.lower()}_{agg['columnName']}",
            })

        if not items:
            return 'SELECT *'

        self._disambiguate_output_names(items)

        select_items = []
        for item in items:
            if item['final_name'] != item['default_name'] or item['explicit'] or item['always_alias']:
                select_items.append(
                    f"{item['expr']} AS {SecurityService.quote_identifier(item['final_name'])}"
                )
            else:
                select_items.append(item['expr'])

        return f'SELECT {", ".join(select_items)}'

    @staticmethod
    def _disambiguate_output_names(items):
        """Guarantee unique, deterministic output column names.

        Colliding implicit names (e.g. the same column name selected from two
        table instances) are qualified with the table alias. Two identical
        explicit aliases are rejected as genuinely ambiguous.
        """
        for item in items:
            item['default_name'] = item['name']
            item['final_name'] = item['name']

        counts = {}
        for item in items:
            counts[item['name']] = counts.get(item['name'], 0) + 1

        for name, count in counts.items():
            if count <= 1:
                continue
            colliding = [i for i in items if i['name'] == name]
            if any(i['explicit'] for i in colliding):
                raise ValueError(f'Duplicate output column alias: {name}')
            for item in colliding:
                item['final_name'] = item['qualifier']

        # Identical qualifier (same column selected twice from one instance):
        # append an occurrence suffix.
        seen = {}
        for item in items:
            name = item['final_name']
            if name in seen:
                seen[name] += 1
                item['final_name'] = f"{name}_{seen[name]}"
            else:
                seen[name] = 1

    # ------------------------------------------------------------------
    # FROM / JOIN
    # ------------------------------------------------------------------
    def _generate_from_and_joins(self):
        tables = self.query_structure.get('tables', [])
        joins = self.query_structure.get('joins', []) or []
        return self._emit_from(tables, joins)

    def _order_tables_topologically(self, tables, joins):
        """Order table instances so that for every LEFT JOIN the left
        instance is emitted before the right one. Ties are broken by the
        canvas (tables[]) order to keep output deterministic.
        """
        index_of = {t['id']: i for i, t in enumerate(tables)}
        indegree = {t['id']: 0 for t in tables}
        outgoing = {t['id']: [] for t in tables}
        for join in joins:
            if join['type'] == 'LEFT':
                left, right = join['leftTableId'], join['rightTableId']
                outgoing[left].append(right)
                indegree[right] += 1

        ready = sorted([tid for tid, deg in indegree.items() if deg == 0], key=index_of.get)
        order = []
        while ready:
            current = ready.pop(0)
            order.append(current)
            for neighbor in outgoing[current]:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    ready.append(neighbor)
                    ready.sort(key=index_of.get)

        if len(order) != len(tables):
            raise ValueError('Circular LEFT JOIN dependencies between table instances')
        return order

    def _emit_from(self, tables, joins):
        tables_by_id = {t['id']: t for t in tables}
        order = self._order_tables_topologically(tables, joins)

        remaining_joins = list(joins)
        emitted = set()

        first = tables_by_id[order[0]]
        parts = [
            f'FROM {SecurityService.quote_identifier(first["tableName"])} '
            f'{SecurityService.quote_identifier(first["alias"])}'
        ]
        emitted.add(first['id'])

        for table_id in order[1:]:
            table = tables_by_id[table_id]
            attach = None
            for join in remaining_joins:
                touches = table_id in (join['leftTableId'], join['rightTableId'])
                other = join['rightTableId'] if join['leftTableId'] == table_id else join['leftTableId']
                if not touches or other not in emitted:
                    continue
                if join['type'] == 'LEFT' and join['leftTableId'] == table_id:
                    # A LEFT join must be attached from its left side; the
                    # topological order prevents this, but stay defensive.
                    continue
                attach = join
                break

            if attach is None:
                # Disconnected component: explicit cross product.
                parts.append(
                    f'CROSS JOIN {SecurityService.quote_identifier(table["tableName"])} '
                    f'{SecurityService.quote_identifier(table["alias"])}'
                )
            else:
                remaining_joins.remove(attach)
                parts.append(self._generate_single_join(attach, new_table_id=table_id))
            emitted.add(table_id)

        if remaining_joins:
            raise ValueError(
                'Join graph contains a cycle; joins between table instances must form a tree'
            )

        return '\n'.join(parts)

    def _generate_single_join(self, join, new_table_id):
        join_type = SecurityService.validate_join_type(join['type'])
        new_table = self._tables_by_id[new_table_id]

        clause = (
            f'{join_type} JOIN {SecurityService.quote_identifier(new_table["tableName"])} '
            f'{SecurityService.quote_identifier(new_table["alias"])}'
        )
        if join_type == 'CROSS':
            return clause

        left_col = self._get_qualified_column(join['leftTableId'], join['leftColumn'])
        right_col = self._get_qualified_column(join['rightTableId'], join['rightColumn'])
        return f'{clause} ON {left_col} = {right_col}'

    # ------------------------------------------------------------------
    # WHERE / HAVING condition trees
    # ------------------------------------------------------------------
    def _generate_condition_section(self, keyword, node):
        if not node:
            return None
        condition_sql = self._generate_condition_tree(node)
        if condition_sql:
            return f'{keyword} {condition_sql}'
        return None

    def _generate_condition_tree(self, node):
        if not isinstance(node, dict):
            raise ValueError('Invalid condition node')

        if 'op' in node and 'children' in node:
            op = SecurityService.validate_logical_op(node['op'])
            children = node.get('children') or []

            if op == 'NOT':
                if len(children) != 1:
                    raise ValueError('NOT group requires exactly one child')
                child_sql = self._generate_condition_tree(children[0])
                if not child_sql:
                    return None
                return f'NOT ({child_sql})'

            children_sql = []
            for child in children:
                child_sql = self._generate_condition_tree(child)
                if child_sql:
                    children_sql.append(child_sql)

            if not children_sql:
                return None
            if len(children_sql) == 1:
                return children_sql[0]
            return f'({f" {op} ".join(children_sql)})'

        if 'cmp' in node:
            return self._generate_clause(node)

        return None

    def _generate_clause(self, node):
        cmp = SecurityService.validate_operator(node['cmp'])

        if cmp in ('IN', 'NOT IN', 'EXISTS', 'NOT EXISTS') and 'subquery' in node:
            return self._generate_subquery_condition(node, cmp)

        if 'columnName' not in node or 'tableId' not in node:
            raise ValueError('Condition clause requires tableId and columnName')

        col = self._get_qualified_column(node['tableId'], node['columnName'])

        # Optional aggregate wrapper, used by HAVING clauses.
        agg_func = node.get('function')
        if agg_func:
            col = f'{SecurityService.validate_aggregation(agg_func)}({col})'

        if cmp in ('IS NULL', 'IS NOT NULL'):
            return f'{col} {cmp}'

        value = SecurityService.validate_value(node.get('value'))

        # NULL compared with = / != is always NULL in SQL; map to the
        # semantically correct IS NULL / IS NOT NULL form.
        if value is None:
            if cmp == '=':
                return f'{col} IS NULL'
            if cmp == '!=':
                return f'{col} IS NOT NULL'
            raise ValueError(f'Operator {cmp} cannot be used with a NULL value')

        if cmp in ('IN', 'NOT IN'):
            if not isinstance(value, (list, tuple)):
                raise ValueError(f'{cmp} operator requires a list value')
            if len(value) == 0:
                # Empty IN is false for every row; empty NOT IN is true.
                return '(1 = 0)' if cmp == 'IN' else '(1 = 1)'
            placeholders = [self.allocator.bind(v) for v in value]
            return f'{col} {cmp} ({", ".join(placeholders)})'

        param = self.allocator.bind(value)
        return f'{col} {cmp} {param}'

    def _generate_subquery_condition(self, node, cmp):
        subquery_structure = node.get('subquery')
        if not subquery_structure:
            raise ValueError('Subquery structure required for subquery condition')

        sub_gen = SQLGenerator(subquery_structure, allocator=self.allocator)
        sub_sql = sub_gen.generate()

        if cmp in ('EXISTS', 'NOT EXISTS'):
            return f'{cmp} (\n{sub_sql}\n)'

        if 'columnName' not in node or 'tableId' not in node:
            raise ValueError('Column name required for IN/NOT IN subquery')
        col = self._get_qualified_column(node['tableId'], node['columnName'])
        return f'{col} {cmp} (\n{sub_sql}\n)'

    # ------------------------------------------------------------------
    # GROUP BY / CTE
    # ------------------------------------------------------------------
    def _generate_group_by(self):
        aggregations = self.query_structure.get('aggregations', []) or []
        if not aggregations:
            return None

        selected_fields = self.query_structure.get('selectedFields', []) or []
        group_by_fields = []

        for field in selected_fields:
            is_aggregated = any(
                agg['tableId'] == field['tableId'] and agg['columnName'] == field['columnName']
                for agg in aggregations
            )
            if not is_aggregated:
                col = self._get_qualified_column(field['tableId'], field['columnName'])
                if col not in group_by_fields:
                    group_by_fields.append(col)

        if group_by_fields:
            return f'GROUP BY {", ".join(group_by_fields)}'
        return None

    def _generate_ctes(self):
        if not self.ctes:
            return None

        cte_parts = []
        for cte in self.ctes:
            cte_name = SecurityService.validate_identifier(cte['name'])
            sub_gen = SQLGenerator(cte['queryStructure'], allocator=self.allocator)
            sub_sql = sub_gen.generate()
            cte_parts.append(f'{SecurityService.quote_identifier(cte_name)} AS (\n{sub_sql}\n)')

        return 'WITH ' + ',\n'.join(cte_parts)
