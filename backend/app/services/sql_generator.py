from app.services.security_service import SecurityService
from app.services.utils import sort_ctes_by_dependency, validate_cte_names, detect_circular_dependency
from copy import deepcopy


class SQLGenerator:
    def __init__(self, query_structure):
        self.query_structure = deepcopy(query_structure)
        self.params = {}
        self.param_counter = 0
        self._tables_by_id = {t['id']: t for t in self.query_structure.get('tables', [])}
        self.ctes = self.query_structure.get('ctes', [])
        if self.ctes:
            validate_cte_names(self.ctes)
            if detect_circular_dependency(self.ctes):
                raise ValueError('Circular dependency detected in CTEs')
            self.ctes = sort_ctes_by_dependency(self.ctes)
        SecurityService.validate_query_structure(self.query_structure)

    def _next_param(self, value):
        self.param_counter += 1
        param_name = f'p{self.param_counter}'
        self.params[param_name] = value
        return f':{param_name}'

    def _get_table_alias(self, table_id):
        table = self._tables_by_id.get(table_id)
        if table:
            return table['alias']
        raise ValueError(f'Table not found: {table_id}')

    def _get_table_name(self, table_id):
        table = self._tables_by_id.get(table_id)
        if table:
            return table['tableName']
        raise ValueError(f'Table not found: {table_id}')

    def _get_qualified_column(self, table_id, column_name):
        alias = self._get_table_alias(table_id)
        col = SecurityService.validate_column_name(column_name)
        return f'{SecurityService.quote_identifier(alias)}.{SecurityService.quote_identifier(col)}'

    def generate(self):
        return self._generate_normal()

    def _generate_normal(self):
        sql_parts = []

        cte_clause = self._generate_ctes()
        if cte_clause:
            sql_parts.append(cte_clause)

        select_clause = self._generate_select()
        sql_parts.append(select_clause)

        from_and_join_clause = self._generate_from_and_joins()
        sql_parts.append(from_and_join_clause)

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

        limit = self.query_structure.get('limit', 100)
        limit = SecurityService.validate_limit(limit)
        sql_parts.append(f'LIMIT {self._next_param(limit)}')

        offset = self.query_structure.get('offset')
        if offset is not None:
            offset = SecurityService.validate_offset(offset)
            sql_parts.append(f'OFFSET {self._next_param(offset)}')

        return '\n'.join(sql_parts)

    def _generate_select(self):
        selected_fields = self.query_structure.get('selectedFields', [])
        aggregations = self.query_structure.get('aggregations', [])

        select_items = []

        for field in selected_fields:
            is_aggregated = any(
                agg['tableId'] == field['tableId'] and agg['columnName'] == field['columnName']
                for agg in aggregations
            )
            if is_aggregated:
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
            if alias:
                select_items.append(f'{func}({col}) AS {SecurityService.quote_identifier(alias)}')
            else:
                agg_col_name = agg['columnName']
                select_items.append(f'{func}({col}) AS {SecurityService.quote_identifier(f"{func.lower()}_{agg_col_name}")}')

        if not select_items:
            select_items = ['*']

        return f'SELECT {", ".join(select_items)}'

    def _generate_from_and_joins(self):
        tables = self.query_structure.get('tables', [])
        joins = self.query_structure.get('joins', [])

        if not tables:
            raise ValueError('No tables selected')

        if not joins:
            first_table = tables[0]
            table_name = SecurityService.validate_table_name(first_table['tableName'])
            alias = SecurityService.validate_identifier(first_table['alias'])
            return f'FROM {SecurityService.quote_identifier(table_name)} {SecurityService.quote_identifier(alias)}'

        return self._generate_from_with_joins(tables, joins)

    def _generate_from_with_joins(self, tables, joins):
        join_graph = self._build_join_graph(tables, joins)
        ordered_tables, ordered_joins = self._order_tables_with_joins(tables, joins, join_graph)

        first_table = ordered_tables[0]
        table_name = SecurityService.validate_table_name(first_table['tableName'])
        alias = SecurityService.validate_identifier(first_table['alias'])
        from_clause = f'FROM {SecurityService.quote_identifier(table_name)} {SecurityService.quote_identifier(alias)}'

        join_parts = []
        for join in ordered_joins:
            join_sql = self._generate_single_join(join)
            join_parts.append(join_sql)

        if join_parts:
            return from_clause + '\n' + '\n'.join(join_parts)
        return from_clause

    def _build_join_graph(self, tables, joins):
        graph = {t['id']: [] for t in tables}
        for join in joins:
            left_id = join['leftTableId']
            right_id = join['rightTableId']
            if left_id not in graph:
                graph[left_id] = []
            if right_id not in graph:
                graph[right_id] = []
            graph[left_id].append({'to': right_id, 'join': join})
            graph[right_id].append({'to': left_id, 'join': join, 'reverse': True})
        return graph

    def _order_tables_with_joins(self, tables, joins, join_graph):
        if not joins:
            return tables, joins

        table_ids_in_order = []
        joins_in_order = []
        visited = set()

        start_table_id = tables[0]['id']

        def dfs(table_id):
            if table_id in visited:
                return
            visited.add(table_id)
            table_ids_in_order.append(table_id)

            for edge in join_graph.get(table_id, []):
                neighbor_id = edge['to']
                if neighbor_id not in visited:
                    join = edge['join']
                    is_reverse = edge.get('reverse', False)
                    join_type = join.get('type', 'INNER')

                    if join_type == 'CROSS':
                        if is_reverse:
                            normalized_join = self._normalize_cross_join(join, reverse=True)
                        else:
                            normalized_join = join
                    else:
                        if is_reverse:
                            normalized_join = self._normalize_join(join, reverse=True)
                        else:
                            normalized_join = join

                    joins_in_order.append(normalized_join)
                    dfs(neighbor_id)

        dfs(start_table_id)

        for table in tables:
            if table['id'] not in visited:
                dfs(table['id'])

        ordered_tables = [next(t for t in tables if t['id'] == tid) for tid in table_ids_in_order]

        return ordered_tables, joins_in_order

    def _normalize_join(self, join, reverse):
        normalized = deepcopy(join)

        if reverse:
            normalized['leftTableId'] = join['rightTableId']
            normalized['leftColumn'] = join['rightColumn']
            normalized['leftTable'] = join['rightTable']
            normalized['rightTableId'] = join['leftTableId']
            normalized['rightColumn'] = join['leftColumn']
            normalized['rightTable'] = join['leftTable']

        return normalized

    def _normalize_cross_join(self, join, reverse):
        normalized = deepcopy(join)
        if reverse:
            normalized['leftTableId'] = join['rightTableId']
            normalized['leftTable'] = join['rightTable']
            normalized['rightTableId'] = join['leftTableId']
            normalized['rightTable'] = join['leftTable']
        return normalized

    def _generate_single_join(self, join):
        join_type = SecurityService.validate_join_type(join['type'])

        if join_type == 'CROSS':
            right_table_name = SecurityService.validate_table_name(join.get('rightTable', ''))
            right_alias = self._get_table_alias(join.get('rightTableId', ''))
            quoted_right_table = SecurityService.quote_identifier(right_table_name)
            quoted_right_alias = SecurityService.quote_identifier(right_alias)
            return f'CROSS JOIN {quoted_right_table} {quoted_right_alias}'

        right_table_name = SecurityService.validate_table_name(join.get('rightTable', ''))
        right_alias = self._get_table_alias(join.get('rightTableId', ''))
        left_col = self._get_qualified_column(join.get('leftTableId', ''), join['leftColumn'])
        right_col = self._get_qualified_column(join.get('rightTableId', ''), join['rightColumn'])

        quoted_right_table = SecurityService.quote_identifier(right_table_name)
        quoted_right_alias = SecurityService.quote_identifier(right_alias)

        return f'{join_type} JOIN {quoted_right_table} {quoted_right_alias} ON {left_col} = {right_col}'

    def _generate_where(self):
        where = self.query_structure.get('where')
        if not where:
            return None
        condition_sql = self._generate_condition_tree(where)
        if condition_sql:
            return f'WHERE {condition_sql}'
        return None

    def _generate_having(self):
        having = self.query_structure.get('having')
        if not having:
            return None
        condition_sql = self._generate_condition_tree(having)
        if condition_sql:
            return f'HAVING {condition_sql}'
        return None

    def _generate_ctes(self):
        if not self.ctes:
            return None

        cte_parts = []
        for cte in self.ctes:
            cte_name = SecurityService.validate_identifier(cte['name'])
            cte_query = cte['queryStructure']

            sub_gen = SQLGenerator(cte_query)
            sub_sql = sub_gen._generate_normal()
            sub_params = sub_gen.get_params()

            param_offset = self.param_counter
            for key, value in sub_params.items():
                new_key = f'p{int(key[1:]) + param_offset}'
                sub_sql = sub_sql.replace(f':{key}', f':{new_key}')
                self.params[new_key] = value
            self.param_counter += len(sub_params)

            cte_parts.append(f'{SecurityService.quote_identifier(cte_name)} AS (\n{sub_sql}\n)')

        return 'WITH ' + ',\n'.join(cte_parts)

    def _generate_condition_tree(self, node):
        if node is None:
            return None

        if 'op' in node and 'children' in node:
            op = node['op']
            if op == 'NOT':
                if not node['children']:
                    return None
                child_sql = self._generate_condition_tree(node['children'][0])
                if not child_sql:
                    return None
                return f'NOT ({child_sql})'

            if op not in ('AND', 'OR'):
                raise ValueError(f'Invalid logical operator: {op}')

            children_sql = []
            for child in node['children']:
                child_sql = self._generate_condition_tree(child)
                if child_sql:
                    children_sql.append(child_sql)

            if not children_sql:
                return None
            if len(children_sql) == 1:
                return children_sql[0]
            return f'({f" {op} ".join(children_sql)})'

        elif 'cmp' in node:
            cmp = node['cmp']

            if cmp in ('EXISTS', 'NOT EXISTS'):
                return self._generate_subquery_condition(node, cmp)

            if cmp in ('IN', 'NOT IN') and 'subquery' in node:
                return self._generate_subquery_condition(node, cmp)

            if 'columnName' not in node:
                return None

            table_id = node['tableId']
            column_name = node['columnName']
            col = self._get_qualified_column(table_id, column_name)

            if cmp in ('IS NULL', 'IS NOT NULL'):
                SecurityService.validate_operator(cmp)
                return f'{col} {cmp}'

            if cmp == 'IN':
                value = node.get('value', [])
                if not isinstance(value, list):
                    raise ValueError('IN operator requires a list value')
                if len(value) == 0:
                    return '(1 = 0)'
                placeholders = [self._next_param(v) for v in value]
                return f'{col} IN ({", ".join(placeholders)})'

            if cmp == 'NOT IN':
                value = node.get('value', [])
                if not isinstance(value, list):
                    raise ValueError('NOT IN operator requires a list value')
                if len(value) == 0:
                    return '(1 = 1)'
                placeholders = [self._next_param(v) for v in value]
                return f'{col} NOT IN ({", ".join(placeholders)})'

            SecurityService.validate_operator(cmp)
            value = SecurityService.validate_value(node.get('value'))

            if cmp == 'LIKE':
                param = self._next_param(value)
                return f'{col} LIKE {param}'

            param = self._next_param(value)
            return f'{col} {cmp} {param}'

        return None

    def _generate_subquery_condition(self, node, cmp):
        subquery_structure = node.get('subquery')
        if not subquery_structure:
            raise ValueError('Subquery structure required for subquery condition')

        sub_gen = SQLGenerator(subquery_structure)
        sub_sql = sub_gen._generate_normal()
        sub_params = sub_gen.get_params()

        param_offset = self.param_counter
        for key, value in sub_params.items():
            new_key = f'p{int(key[1:]) + param_offset}'
            sub_sql = sub_sql.replace(f':{key}', f':{new_key}')
            self.params[new_key] = value
        self.param_counter += len(sub_params)

        if cmp in ('EXISTS', 'NOT EXISTS'):
            return f'{cmp} (\n{sub_sql}\n)'
        else:
            if 'columnName' not in node:
                raise ValueError('Column name required for IN/NOT IN subquery')
            table_id = node['tableId']
            column_name = node['columnName']
            col = self._get_qualified_column(table_id, column_name)
            SecurityService.validate_operator(cmp)
            return f'{col} {cmp} (\n{sub_sql}\n)'

    def _generate_group_by(self):
        aggregations = self.query_structure.get('aggregations', [])
        if not aggregations:
            return None

        selected_fields = self.query_structure.get('selectedFields', [])
        group_by_fields = []

        for field in selected_fields:
            is_aggregated = any(
                agg['tableId'] == field['tableId'] and agg['columnName'] == field['columnName']
                for agg in aggregations
            )
            if not is_aggregated:
                col = self._get_qualified_column(field['tableId'], field['columnName'])
                group_by_fields.append(col)

        if group_by_fields:
            return f'GROUP BY {", ".join(group_by_fields)}'
        return None

    def _generate_order_by(self):
        order_by = self.query_structure.get('orderBy', [])
        if not order_by:
            return None

        order_parts = []
        for item in order_by:
            col = self._get_qualified_column(item['tableId'], item['columnName'])
            direction = SecurityService.validate_order_direction(item.get('direction', 'ASC'))
            order_parts.append(f'{col} {direction}')

        return f'ORDER BY {", ".join(order_parts)}'

    def get_params(self):
        return self.params
