import re

class SecurityService:
    ALLOWED_OPERATORS = {'=', '!=', '>', '<', '>=', '<=', 'LIKE', 'IN', 'NOT IN', 'EXISTS', 'NOT EXISTS'}
    ALLOWED_JOIN_TYPES = {'INNER', 'LEFT', 'RIGHT', 'FULL'}
    ALLOWED_AGGREGATIONS = {'SUM', 'AVG', 'COUNT', 'MAX', 'MIN'}
    SQL_KEYWORDS = {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'UNION', 'EXEC', 'EXECUTE', 'XP_'}
    
    @staticmethod
    def validate_operator(op):
        if op not in SecurityService.ALLOWED_OPERATORS:
            raise ValueError(f'Invalid operator: {op}')
        return op
    
    @staticmethod
    def validate_identifier(name):
        if not name:
            raise ValueError('Identifier cannot be empty')
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
            raise ValueError(f'Invalid identifier: {name}')
        return name
    
    @staticmethod
    def quote_identifier(name):
        return f'"{name}"'
    
    @staticmethod
    def validate_join_type(join_type):
        if join_type not in SecurityService.ALLOWED_JOIN_TYPES:
            raise ValueError(f'Invalid join type: {join_type}')
        return join_type
    
    @staticmethod
    def validate_aggregation(agg_func):
        if agg_func not in SecurityService.ALLOWED_AGGREGATIONS:
            raise ValueError(f'Invalid aggregation function: {agg_func}')
        return agg_func
    
    @staticmethod
    def validate_table_name(table_name):
        if not table_name:
            raise ValueError('Table name cannot be empty')
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
            raise ValueError(f'Invalid table name: {table_name}')
        return table_name
    
    @staticmethod
    def validate_column_name(column_name):
        if not column_name:
            raise ValueError('Column name cannot be empty')
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column_name):
            raise ValueError(f'Invalid column name: {column_name}')
        return column_name
    
    @staticmethod
    def validate_alias(alias):
        if alias:
            SecurityService.validate_identifier(alias)
        return alias
    
    @staticmethod
    def validate_value(value):
        return value
    
    @staticmethod
    def validate_limit(limit):
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError('Limit must be an integer between 1 and 1000')
        return limit
