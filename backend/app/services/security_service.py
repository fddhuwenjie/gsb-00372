import re

class SecurityService:
    ALLOWED_OPERATORS = {
        '=', '!=', '>', '<', '>=', '<=',
        'LIKE', 'IN', 'NOT IN',
        'IS NULL', 'IS NOT NULL',
        'EXISTS', 'NOT EXISTS',
    }
    # SQLite does not support RIGHT JOIN / FULL JOIN. They are rejected
    # explicitly instead of being silently rewritten.
    ALLOWED_JOIN_TYPES = {'INNER', 'LEFT', 'CROSS'}
    UNSUPPORTED_JOIN_TYPES = {'RIGHT', 'FULL'}
    ALLOWED_AGGREGATIONS = {'SUM', 'AVG', 'COUNT', 'MAX', 'MIN'}
    ALLOWED_LOGICAL_OPS = {'AND', 'OR', 'NOT'}

    # Keywords that may never appear in an executable statement.
    FORBIDDEN_STATEMENT_KEYWORDS = {
        'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'DROP', 'ALTER', 'CREATE',
        'PRAGMA', 'ATTACH', 'DETACH', 'VACUUM', 'REINDEX', 'ANALYZE',
        'TRIGGER', 'GRANT', 'REVOKE', 'BEGIN', 'COMMIT', 'ROLLBACK',
        'SAVEPOINT', 'RELEASE', 'TRANSACTION',
    }

    _QUOTED_SPAN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\[[^\]]*\]')
    _KEYWORD_RE = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b')

    @staticmethod
    def validate_operator(op):
        if op not in SecurityService.ALLOWED_OPERATORS:
            raise ValueError(f'Invalid operator: {op}')
        return op

    @staticmethod
    def validate_logical_op(op):
        if op not in SecurityService.ALLOWED_LOGICAL_OPS:
            raise ValueError(f'Invalid logical operator: {op}')
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
        SecurityService.validate_identifier(name)
        return f'"{name}"'

    @staticmethod
    def validate_join_type(join_type):
        if join_type in SecurityService.UNSUPPORTED_JOIN_TYPES:
            raise ValueError(
                f'{join_type} JOIN is not supported by SQLite and is rejected. '
                'Use INNER, LEFT or CROSS JOIN instead.'
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
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError('Limit must be an integer between 1 and 1000')
        if limit < 1 or limit > 1000:
            raise ValueError('Limit must be an integer between 1 and 1000')
        return limit

    @staticmethod
    def validate_offset(offset):
        if offset is None:
            return 0
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise ValueError('Offset must be a non-negative integer')
        if offset < 0:
            raise ValueError('Offset must be a non-negative integer')
        return offset

    @staticmethod
    def validate_read_only_sql(sql):
        """Validate that a generated SQL string is a single read-only statement.

        Defense in depth: the generator only produces SELECT statements from a
        validated AST and all user values travel via bound parameters, so the
        SQL text itself must contain no comments, no statement separators, no
        write keywords (including data-modifying CTEs) and no PRAGMA.
        """
        if not sql or not sql.strip():
            raise ValueError('Empty SQL statement')

        # Strip quoted identifiers / literals so keyword scanning cannot be
        # fooled by (or miss) tokens hidden inside quotes.
        stripped = SecurityService._QUOTED_SPAN_RE.sub(' ', sql)

        if '--' in stripped or '/*' in stripped or '*/' in stripped:
            raise ValueError('SQL comments are not allowed in executable statements')

        body = stripped.strip()
        if body.endswith(';'):
            body = body[:-1]
        if ';' in body:
            raise ValueError('Multiple SQL statements are not allowed')

        tokens = SecurityService._KEYWORD_RE.findall(body)
        if not tokens:
            raise ValueError('Empty SQL statement')

        first = tokens[0].upper()
        if first not in ('SELECT', 'WITH', 'EXPLAIN'):
            raise ValueError(f'Only read-only SELECT statements are allowed, got: {first}')

        for token in tokens:
            if token.upper() in SecurityService.FORBIDDEN_STATEMENT_KEYWORDS:
                raise ValueError(f'Forbidden SQL keyword in read-only query: {token.upper()}')

        return sql
