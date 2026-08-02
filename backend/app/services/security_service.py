import re

class SecurityService:
    # Comparison operators usable in WHERE/HAVING leaves.
    ALLOWED_OPERATORS = {
        '=', '!=', '>', '<', '>=', '<=', 'LIKE', 'NOT LIKE',
        'IN', 'NOT IN', 'IS NULL', 'IS NOT NULL', 'EXISTS', 'NOT EXISTS',
    }
    # Logical operators for the condition tree.
    ALLOWED_LOGICAL = {'AND', 'OR', 'NOT'}
    # SQLite supports these physical joins. RIGHT/FULL are intentionally
    # excluded and must be rejected explicitly (SQLite cannot execute them).
    ALLOWED_JOIN_TYPES = {'INNER', 'LEFT', 'CROSS'}
    REJECTED_JOIN_TYPES = {'RIGHT', 'FULL'}
    ALLOWED_AGGREGATIONS = {'SUM', 'AVG', 'COUNT', 'MAX', 'MIN'}
    ALLOWED_SORT_DIRECTIONS = {'ASC', 'DESC'}

    IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

    MAX_LIMIT = 1000
    MAX_OFFSET = 1_000_000

    @staticmethod
    def validate_operator(op):
        if op not in SecurityService.ALLOWED_OPERATORS:
            raise ValueError(f'Invalid operator: {op}')
        return op

    @staticmethod
    def validate_logical(op):
        if op not in SecurityService.ALLOWED_LOGICAL:
            raise ValueError(f'Invalid logical operator: {op}')
        return op

    @staticmethod
    def validate_identifier(name):
        if not name:
            raise ValueError('Identifier cannot be empty')
        if not SecurityService.IDENTIFIER_RE.match(name):
            raise ValueError(f'Invalid identifier: {name}')
        return name

    @staticmethod
    def quote_identifier(name):
        # Reject embedded quotes defensively, then double-quote.
        if '"' in name:
            raise ValueError(f'Invalid identifier: {name}')
        return f'"{name}"'

    @staticmethod
    def validate_join_type(join_type):
        if join_type in SecurityService.REJECTED_JOIN_TYPES:
            raise ValueError(
                f'{join_type} JOIN is not supported by SQLite and is rejected'
            )
        if join_type not in SecurityService.ALLOWED_JOIN_TYPES:
            raise ValueError(f'Invalid join type: {join_type}')
        return join_type

    @staticmethod
    def validate_aggregation(agg_func):
        if agg_func not in SecurityService.ALLOWED_AGGREGATIONS:
            raise ValueError(f'Invalid aggregation function: {agg_func}')
        return agg_func

    @staticmethod
    def validate_sort_direction(direction):
        d = (direction or 'ASC').upper()
        if d not in SecurityService.ALLOWED_SORT_DIRECTIONS:
            raise ValueError(f'Invalid sort direction: {direction}')
        return d

    @staticmethod
    def validate_table_name(table_name):
        if not table_name:
            raise ValueError('Table name cannot be empty')
        if not SecurityService.IDENTIFIER_RE.match(table_name):
            raise ValueError(f'Invalid table name: {table_name}')
        return table_name

    @staticmethod
    def validate_column_name(column_name):
        if not column_name:
            raise ValueError('Column name cannot be empty')
        if not SecurityService.IDENTIFIER_RE.match(column_name):
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
        if limit is None:
            return 100
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError('Limit must be an integer')
        if limit < 1 or limit > SecurityService.MAX_LIMIT:
            raise ValueError(
                f'Limit must be between 1 and {SecurityService.MAX_LIMIT}'
            )
        return limit

    @staticmethod
    def validate_offset(offset):
        if offset is None:
            return 0
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise ValueError('Offset must be an integer')
        if offset < 0 or offset > SecurityService.MAX_OFFSET:
            raise ValueError(
                f'Offset must be between 0 and {SecurityService.MAX_OFFSET}'
            )
        return offset
