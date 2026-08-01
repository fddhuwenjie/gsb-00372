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
    
    def _has_full_join(self):
        joins = self.query_structure.get('joins', [])
        return any(j.get('type') == 'FULL' for j in joins)
    
    def generate(self):
        if self._has_full_join():
            return self._generate_full_join_union()
        else:
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
        
        order_by_clause = self._generate_order_by()
        if order_by_clause:
            sql_parts.append(order_by_clause)
        
        limit = self.query_structure.get('limit', 100)
        sql_parts.append(f'LIMIT {SecurityService.validate_limit(limit)}')
        
        return '\n'.join(sql_parts)
    
    def _generate_full_join_union(self):
        joins = self.query_structure.get('joins', [])
        full_joins = [j for j in joins if j.get('type') == 'FULL']
        
        if len(full_joins) > 1:
            raise ValueError('Multiple FULL JOINs are not supported')
        
        full_join = full_joins[0]
        
        left_query = deepcopy(self.query_structure)
        left_query['joins'] = [
            {**j, 'type': 'LEFT'} if j['id'] == full_join['id'] else j
            for j in left_query['joins']
        ]
        
        right_query = self._create_swapped_query(full_join)
        
        left_gen = SQLGenerator(left_query)
        left_sql = left_gen._generate_normal()
        left_params = left_gen.get_params()
        
        right_gen = SQLGenerator(right_query)
        right_sql = right_gen._generate_normal()
        right_params = right_gen.get_params()
        
        param_offset = len(left_params)
        for key, value in right_params.items():
            new_key = f'p{int(key[1:]) + param_offset}'
            right_sql = right_sql.replace(f':{key}', f':{new_key}')
            self.params[new_key] = value
        
        for key, value in left_params.items():
            self.params[key] = value
        
        left_sql_no_limit = left_sql.rsplit('\nLIMIT', 1)[0]
        right_sql_no_limit = right_sql.rsplit('\nLIMIT', 1)[0]
        
        limit = self.query_structure.get('limit', 100)
        
        return f'{left_sql_no_limit}\nUNION\n{right_sql_no_limit}\nLIMIT {SecurityService.validate_limit(limit)}'
    
    def _create_swapped_query(self, full_join):
        swapped = deepcopy(self.query_structure)
        
        left_id = full_join['leftTableId']
        right_id = full_join['rightTableId']
        
        tables = swapped['tables']
        left_idx = next(i for i, t in enumerate(tables) if t['id'] == left_id)
        right_idx = next(i for i, t in enumerate(tables) if t['id'] == right_id)
        
        tables[left_idx], tables[right_idx] = tables[right_idx], tables[left_idx]
        
        for j in swapped['joins']:
            if j['id'] == full_join['id']:
                j['type'] = 'LEFT'
                j['leftTableId'], j['rightTableId'] = right_id, left_id
                j['leftColumn'], j['rightColumn'] = full_join['rightColumn'], full_join['leftColumn']
                j['leftTable'], j['rightTable'] = full_join['rightTable'], full_join['leftTable']
            else:
                pass
        
        return swapped
    
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
            graph[left_id].append({'to': right_id, 'join': join})
            graph[right_id].append({'to': left_id, 'join': join, 'reverse': True})
        return graph
    
    def _order_tables_with_joins(self, tables, joins, join_graph):
        right_joins = [j for j in joins if j.get('type') == 'RIGHT']
        
        if not right_joins:
            return tables, joins
        
        table_ids_in_order = []
        joins_in_order = []
        visited = set()
        
        start_table_id = right_joins[0]['rightTableId']
        
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
                    
                    if is_reverse or join.get('type') == 'RIGHT':
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
        
        if normalized['type'] == 'RIGHT':
            normalized['type'] = 'LEFT'
        
        return normalized
    
    def _generate_single_join(self, join):
        join_type = SecurityService.validate_join_type(join['type'])
        right_table_name = SecurityService.validate_table_name(join['rightTable'])
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
            
            param_offset = len(self.params)
            for key, value in sub_params.items():
                new_key = f'p{int(key[1:]) + param_offset}'
                sub_sql = sub_sql.replace(f':{key}', f':{new_key}')
                self.params[new_key] = value
            
            cte_parts.append(f'{SecurityService.quote_identifier(cte_name)} AS (\n{sub_sql}\n)')
        
        return 'WITH ' + ',\n'.join(cte_parts)
    
    def _generate_condition_tree(self, node):
        if 'op' in node and 'children' in node:
            op = node['op']
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
            cmp = SecurityService.validate_operator(node['cmp'])
            
            if cmp in ('IN', 'NOT IN', 'EXISTS', 'NOT EXISTS') and 'subquery' in node:
                return self._generate_subquery_condition(node, cmp)
            
            if 'columnName' in node:
                table_id = node['tableId']
                column_name = node['columnName']
                value = SecurityService.validate_value(node['value'])
                
                col = self._get_qualified_column(table_id, column_name)
                
                if cmp == 'IN':
                    if not isinstance(value, list):
                        raise ValueError('IN operator requires a list value')
                    placeholders = [self._next_param(v) for v in value]
                    return f'{col} IN ({", ".join(placeholders)})'
                elif cmp == 'NOT IN':
                    if not isinstance(value, list):
                        raise ValueError('NOT IN operator requires a list value')
                    placeholders = [self._next_param(v) for v in value]
                    return f'{col} NOT IN ({", ".join(placeholders)})'
                elif cmp == 'LIKE':
                    param = self._next_param(value)
                    return f'{col} LIKE {param}'
                else:
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
        
        param_offset = len(self.params)
        for key, value in sub_params.items():
            new_key = f'p{int(key[1:]) + param_offset}'
            sub_sql = sub_sql.replace(f':{key}', f':{new_key}')
            self.params[new_key] = value
        
        if cmp in ('EXISTS', 'NOT EXISTS'):
            return f'{cmp} (\n{sub_sql}\n)'
        else:
            if 'columnName' not in node:
                raise ValueError('Column name required for IN/NOT IN subquery')
            table_id = node['tableId']
            column_name = node['columnName']
            col = self._get_qualified_column(table_id, column_name)
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
        return None
    
    def get_params(self):
        return self.params
