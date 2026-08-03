import re


class SecurityService:
    ALLOWED_OPERATORS = {
        '=', '!=', '>', '<', '>=', '<=',
        'LIKE', 'IN', 'NOT IN',
        'IS NULL', 'IS NOT NULL',
        'EXISTS', 'NOT EXISTS',
    }
    ALLOWED_JOIN_TYPES = {'INNER', 'LEFT', 'CROSS'}
    REJECTED_JOIN_TYPES = {'RIGHT', 'FULL'}
    ALLOWED_AGGREGATIONS = {'SUM', 'AVG', 'COUNT', 'MAX', 'MIN'}
    ALLOWED_ORDER_DIRECTIONS = {'ASC', 'DESC'}

    WRITE_KEYWORDS = re.compile(
        r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|VACUUM|REINDEX)\b',
        re.IGNORECASE,
    )
    PRAGMA_DANGEROUS = re.compile(
        r'\bPRAGMA\s+(?!(?:foreign_keys|journal_mode|synchronous|table_info|database_list|index_list|index_info)\b)',
        re.IGNORECASE,
    )
    COMMENT_PATTERNS = [
        re.compile(r'--'),
        re.compile(r'/\*'),
        re.compile(r'\*/'),
    ]
    MULTI_STATEMENT = re.compile(r';\s*\S')

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
        if join_type in SecurityService.REJECTED_JOIN_TYPES:
            raise ValueError(
                f'{join_type} JOIN is not supported by SQLite. '
                f'Please use INNER, LEFT, or CROSS JOIN.'
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
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float, str)):
            return value
        if isinstance(value, list):
            return [SecurityService.validate_value(v) for v in value]
        raise ValueError(f'Unsupported value type: {type(value).__name__}')

    @staticmethod
    def validate_limit(limit):
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError('Limit must be an integer between 1 and 1000')
        return limit

    @staticmethod
    def validate_offset(offset):
        if not isinstance(offset, int) or offset < 0:
            raise ValueError('Offset must be a non-negative integer')
        return offset

    @staticmethod
    def validate_order_direction(direction):
        direction = direction.upper()
        if direction not in SecurityService.ALLOWED_ORDER_DIRECTIONS:
            raise ValueError(f'Invalid order direction: {direction}')
        return direction

    @staticmethod
    def _strip_quoted(sql):
        result = []
        in_quote = False
        i = 0
        while i < len(sql):
            ch = sql[i]
            if ch == '"':
                if in_quote and i + 1 < len(sql) and sql[i + 1] == '"':
                    i += 2
                    continue
                in_quote = not in_quote
                i += 1
                continue
            if not in_quote:
                result.append(ch)
            i += 1
        return ''.join(result)

    @staticmethod
    def validate_readonly_sql(sql):
        if not sql or not sql.strip():
            raise ValueError('Empty SQL is not allowed')

        stripped = sql.strip()
        unquoted = SecurityService._strip_quoted(stripped)

        if SecurityService.WRITE_KEYWORDS.search(unquoted):
            match = SecurityService.WRITE_KEYWORDS.search(unquoted)
            raise ValueError(f'Write operations are not allowed: found {match.group(0)}')

        if SecurityService.PRAGMA_DANGEROUS.search(unquoted):
            raise ValueError('Dangerous PRAGMA statements are not allowed')

        for pattern in SecurityService.COMMENT_PATTERNS:
            if pattern.search(unquoted):
                raise ValueError('SQL comments are not allowed in generated queries')

        if SecurityService.MULTI_STATEMENT.search(unquoted):
            raise ValueError('Multiple SQL statements are not allowed')

        if not re.match(r'^\s*(SELECT|WITH|EXPLAIN)\b', stripped, re.IGNORECASE):
            raise ValueError('Only SELECT/WITH/EXPLAIN queries are allowed')

        return True

    @staticmethod
    def validate_query_structure(query_structure):
        if not isinstance(query_structure, dict):
            raise ValueError('Query structure must be an object')

        tables = query_structure.get('tables', [])
        if not tables:
            raise ValueError('At least one table is required')

        seen_ids = set()
        for table in tables:
            tid = table.get('id')
            if not tid:
                raise ValueError('Table instance id is required')
            if tid in seen_ids:
                raise ValueError(f'Duplicate table instance id: {tid}')
            seen_ids.add(tid)
            SecurityService.validate_table_name(table.get('tableName', ''))
            SecurityService.validate_identifier(table.get('alias', ''))

        joins = query_structure.get('joins', [])
        for join in joins:
            SecurityService.validate_join_type(join.get('type', ''))

        def check_no_template_refs(node, path='root'):
            if isinstance(node, dict):
                if '$param' in node:
                    raise ValueError(f'Uninstantiated template parameter at {path}')
                if 'paramRef' in node:
                    raise ValueError(f'Uninstantiated template paramRef at {path}')
                if node.get('cmp') == 'BETWEEN':
                    raise ValueError(f'BETWEEN operator must be expanded from a template at {path}')
                for key, value in node.items():
                    check_no_template_refs(value, f'{path}.{key}')
            elif isinstance(node, list):
                for i, item in enumerate(node):
                    check_no_template_refs(item, f'{path}[{i}]')

        check_no_template_refs(query_structure)

        return True
