import re


class SecurityService:
    """
    Central validation + execution security for the visual query builder.

    The backend is the single source of truth for SQL generation and execution
    semantics. This class only validates *structure* supplied by the AST; no raw
    user text is ever interpolated into SQL except through bound parameters.
    """

    ALLOWED_OPERATORS = {
        '=', '!=', '<>', '>', '<', '>=', '<=',
        'LIKE', 'NOT LIKE',
        'IN', 'NOT IN',
        'IS NULL', 'IS NOT NULL',
        'EXISTS', 'NOT EXISTS',
    }
    ALLOWED_JOIN_TYPES = {'INNER', 'LEFT', 'CROSS'}
    REJECTED_JOIN_TYPES = {'RIGHT', 'FULL', 'RIGHT OUTER', 'FULL OUTER'}
    ALLOWED_AGGREGATIONS = {'SUM', 'AVG', 'COUNT', 'MAX', 'MIN'}
    ALLOWED_LOGICAL_OPS = {'AND', 'OR'}
    ALLOWED_UNARY_OPS = {'NOT'}

    MAX_LIMIT = 1000
    MAX_OFFSET = 1_000_000
    MAX_PARAMS = 500
    QUERY_TIMEOUT_SECONDS = 10
    MAX_ROWS = 1000

    ALLOWED_PARAM_TYPES = {
        'string', 'integer', 'number', 'boolean', 'date', 'datetime',
        'string_list', 'integer_list', 'number_list', 'date_list',
    }
    ALLOWED_PARAM_USAGES = {'filter', 'limit', 'offset', 'date_window_start', 'date_window_end'}

    _IDENT_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    _PARAM_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    _WRITE_RE = re.compile(
        r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|'
        r'ATTACH|DETACH|VACUUM|REINDEX|PRAGMA|GRANT|REVOKE|MERGE)\b',
        re.IGNORECASE,
    )
    _WRITE_CTE_RE = re.compile(
        r'\b(INSERT|UPDATE|DELETE|REPLACE)\b', re.IGNORECASE
    )
    _TRANSACTION_RE = re.compile(
        r'\b(BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\b', re.IGNORECASE
    )

    @staticmethod
    def validate_operator(op):
        if op not in SecurityService.ALLOWED_OPERATORS:
            raise ValueError(f'Invalid operator: {op}')
        return op

    @staticmethod
    def validate_join_type(join_type):
        if join_type in SecurityService.REJECTED_JOIN_TYPES:
            raise ValueError(
                f'JOIN type {join_type} is not supported by SQLite. '
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
    def validate_identifier(name):
        if name is None:
            raise ValueError('Identifier cannot be None')
        if not isinstance(name, str) or not name:
            raise ValueError('Identifier cannot be empty')
        if not SecurityService._IDENT_RE.match(name):
            raise ValueError(f'Invalid identifier: {name}')
        return name

    validate_table_name = validate_identifier
    validate_column_name = validate_identifier

    @staticmethod
    def validate_alias(alias):
        if alias is None or alias == '':
            return None
        return SecurityService.validate_identifier(alias)

    @staticmethod
    def validate_table_instance(table):
        if not isinstance(table, dict):
            raise ValueError('Table instance must be an object')
        SecurityService.validate_identifier(table.get('id'))
        SecurityService.validate_identifier(table.get('tableName'))
        alias = table.get('alias')
        if alias is not None and alias != '':
            SecurityService.validate_identifier(alias)
        return table

    @staticmethod
    def quote_identifier(name):
        SecurityService.validate_identifier(name)
        return f'"{name}"'

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

    @staticmethod
    def validate_scalar_value(value):
        """Validate a bound parameter value (JSON-serialisable scalar)."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, (list, tuple, dict)):
            raise ValueError('Nested values must be supplied as explicit lists')
        return value

    @staticmethod
    def validate_in_value(value):
        if not isinstance(value, list):
            raise ValueError('IN operator requires a list value')
        if len(value) > SecurityService.MAX_PARAMS:
            raise ValueError('Too many values in IN list')
        return [SecurityService.validate_scalar_value(v) for v in value]

    @staticmethod
    def validate_ast_structure(query_structure):
        """
        Walk the user-supplied AST and validate every identifier/operator.
        This is called before SQL generation so malformed ASTs fail fast and
        no raw text ever reaches the SQL string.
        """
        if not isinstance(query_structure, dict):
            raise ValueError('Query structure must be an object')

        tables = query_structure.get('tables', [])
        if not isinstance(tables, list) or not tables:
            raise ValueError('At least one table is required')

        table_ids = set()
        aliases = set()
        for table in tables:
            SecurityService.validate_table_instance(table)
            tid = table['id']
            if tid in table_ids:
                raise ValueError(f'Duplicate table instance id: {tid}')
            table_ids.add(tid)
            alias = table.get('alias') or tid
            if alias in aliases:
                raise ValueError(f'Duplicate table alias: {alias}')
            aliases.add(alias)

        for join in query_structure.get('joins', []):
            SecurityService._validate_join(join, table_ids)

        for field in query_structure.get('selectedFields', []):
            SecurityService._validate_field_ref(field, table_ids, 'selectedField')

        for agg in query_structure.get('aggregations', []):
            SecurityService._validate_field_ref(agg, table_ids, 'aggregation')
            SecurityService.validate_aggregation(agg.get('function'))

        where = query_structure.get('where')
        if where is not None:
            SecurityService._validate_condition(where, table_ids)

        having = query_structure.get('having')
        if having is not None:
            SecurityService._validate_condition(having, table_ids)

        for order in query_structure.get('orderBy', []):
            SecurityService._validate_order_by(order, table_ids)

        SecurityService.validate_limit(query_structure.get('limit', 100))
        SecurityService.validate_offset(query_structure.get('offset', 0))

        for cte in query_structure.get('ctes', []) or []:
            SecurityService.validate_identifier(cte.get('name'))
            SecurityService.validate_ast_structure(cte.get('queryStructure'))

        return True

    @staticmethod
    def _validate_join(join, table_ids):
        if not isinstance(join, dict):
            raise ValueError('Join must be an object')
        SecurityService.validate_identifier(join.get('id'))
        SecurityService.validate_join_type(join.get('type'))
        if join.get('leftTableId') not in table_ids:
            raise ValueError('JOIN references unknown left table')
        if join.get('rightTableId') not in table_ids:
            raise ValueError('JOIN references unknown right table')
        if join['type'] != 'CROSS':
            SecurityService.validate_column_name(join.get('leftColumn'))
            SecurityService.validate_column_name(join.get('rightColumn'))
        SecurityService.validate_table_name(join.get('leftTable'))
        SecurityService.validate_table_name(join.get('rightTable'))

    @staticmethod
    def _validate_field_ref(field, table_ids, label):
        if not isinstance(field, dict):
            raise ValueError(f'{label} must be an object')
        if field.get('tableId') not in table_ids:
            raise ValueError(f'{label} references unknown table instance')
        SecurityService.validate_column_name(field.get('columnName'))
        alias = field.get('alias')
        if alias:
            SecurityService.validate_alias(alias)

    @staticmethod
    def _validate_order_by(order, table_ids):
        if not isinstance(order, dict):
            raise ValueError('orderBy entry must be an object')
        SecurityService._validate_field_ref(order, table_ids, 'orderBy')
        direction = (order.get('direction') or 'ASC').upper()
        if direction not in ('ASC', 'DESC'):
            raise ValueError(f'Invalid ORDER BY direction: {direction}')

    @staticmethod
    def _validate_condition(node, table_ids):
        if not isinstance(node, dict):
            raise ValueError('Condition node must be an object')

        if node.get('op') in SecurityService.ALLOWED_LOGICAL_OPS:
            children = node.get('children', [])
            if not isinstance(children, list):
                raise ValueError('Logical condition children must be a list')
            for child in children:
                SecurityService._validate_condition(child, table_ids)
            return

        if node.get('op') in SecurityService.ALLOWED_UNARY_OPS:
            child = node.get('child')
            if child is None:
                raise ValueError('NOT condition requires a child')
            SecurityService._validate_condition(child, table_ids)
            return

        cmp = node.get('cmp')
        if cmp is None:
            raise ValueError('Condition node must have "cmp" or "op"')
        SecurityService.validate_operator(cmp)

        if cmp in ('EXISTS', 'NOT EXISTS'):
            sub = node.get('subquery')
            if sub is None:
                raise ValueError(f'{cmp} requires a subquery')
            SecurityService.validate_ast_structure(sub)
            return

        SecurityService._validate_field_ref(node, table_ids, 'condition')
        if node.get('function'):
            SecurityService.validate_aggregation(node['function'])

        # A condition leaf may reference a declared template parameter by
        # name instead of carrying an inline value. In that case the value
        # is supplied at instantiation time and bound as a parameter; the
        # AST structure itself remains fixed.
        param_ref = node.get('param')
        if param_ref is not None:
            SecurityService.validate_param_name(param_ref)

        if cmp in ('IN', 'NOT IN'):
            if 'subquery' in node and node['subquery'] is not None:
                SecurityService.validate_ast_structure(node['subquery'])
            elif param_ref is None:
                SecurityService.validate_in_value(node.get('value'))
        elif cmp in ('IS NULL', 'IS NOT NULL'):
            return
        elif cmp not in ('EXISTS', 'NOT EXISTS') and param_ref is None:
            SecurityService.validate_scalar_value(node.get('value'))

    @staticmethod
    def audit_sql_text(sql):
        """
        Final defensive gate on the generated SQL text. The AST validator
        already prevents writes, but this protects against future generator
        bugs and comment-based bypass attempts.
        """
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError('Empty SQL')

        stripped = sql.strip()
        if not stripped.upper().startswith(('SELECT', 'WITH', 'EXPLAIN')):
            raise ValueError('Only read-only SELECT queries are allowed')

        # Reject inline comments which can be used to smuggle statements.
        # Bound parameters are the only injection mechanism; quoting inside
        # a value is fine because values never appear in the SQL text.
        if '--' in stripped or '/*' in stripped or '*/' in stripped:
            raise ValueError('SQL comments are not allowed')

        # Reject semicolons that would allow multi-statement execution.
        # A trailing semicolon is acceptable; multiple are not.
        body = stripped.rstrip(';').strip()
        if ';' in body:
            raise ValueError('Multiple SQL statements are not allowed')

        if SecurityService._TRANSACTION_RE.search(body):
            raise ValueError('Transaction control statements are not allowed')

        if SecurityService._WRITE_RE.search(body):
            raise ValueError('Only read-only queries are allowed')

        return True

    # ------------------------------------------------------------------
    # Template parameter validation
    # ------------------------------------------------------------------
    @staticmethod
    def validate_param_name(name):
        if not name or not isinstance(name, str):
            raise ValueError('Parameter name is required')
        if not SecurityService._PARAM_NAME_RE.match(name):
            raise ValueError(f'Invalid parameter name: {name}')
        return name

    @staticmethod
    def validate_param_type(param_type):
        if param_type not in SecurityService.ALLOWED_PARAM_TYPES:
            raise ValueError(
                f'Invalid parameter type: {param_type}. '
                f'Allowed: {sorted(SecurityService.ALLOWED_PARAM_TYPES)}'
            )
        return param_type

    @staticmethod
    def validate_param_declaration(param):
        """Validate a single declared template parameter."""
        if not isinstance(param, dict):
            raise ValueError('Parameter declaration must be an object')
        name = SecurityService.validate_param_name(param.get('name'))
        SecurityService.validate_param_type(param.get('type'))
        label = param.get('label')
        if label is not None and not isinstance(label, str):
            raise ValueError(f'Parameter {name}: label must be a string')
        required = bool(param.get('required', False))
        default = param.get('default')
        if not required and default is None and param.get('type') not in (
            'string_list', 'integer_list', 'number_list', 'date_list'
        ):
            # Non-required scalar params should have a default so queries
            # remain executable. List params default to [] when omitted.
            pass
        if default is not None:
            SecurityService.coerce_param_value(default, param['type'], name)
        # Optional binding to a table instance + column for type/schema
        # migration checking.
        if param.get('tableId') or param.get('columnName'):
            if not param.get('tableId') or not param.get('columnName'):
                raise ValueError(
                    f'Parameter {name}: tableId and columnName must be '
                    f'supplied together'
                )
            SecurityService.validate_column_name(param['columnName'])
        usage = param.get('usage', 'filter')
        if usage not in SecurityService.ALLOWED_PARAM_USAGES:
            raise ValueError(
                f'Parameter {name}: invalid usage {usage}'
            )
        return param

    @staticmethod
    def coerce_param_value(value, param_type, param_name='value'):
        """
        Validate (and where possible coerce) a runtime value against a
        declared parameter type. Raises ValueError with a locatable name
        on mismatch.
        """
        is_list = param_type.endswith('_list')
        base_type = param_type[:-5] if is_list else param_type

        if is_list:
            if value is None:
                return []
            if not isinstance(value, list):
                raise ValueError(
                    f'Parameter {param_name}: expected list for type '
                    f'{param_type}, got {type(value).__name__}'
                )
            return [
                SecurityService._coerce_scalar(v, base_type, param_name, i)
                for i, v in enumerate(value)
            ]
        if value is None:
            return None
        return SecurityService._coerce_scalar(value, base_type, param_name)

    @staticmethod
    def _coerce_scalar(value, base_type, param_name, index=None):
        label = f'{param_name}[{index}]' if index is not None else param_name
        if base_type == 'string':
            if not isinstance(value, str):
                raise ValueError(
                    f'Parameter {label}: expected string, got '
                    f'{type(value).__name__}'
                )
            return value
        if base_type == 'integer':
            if isinstance(value, bool):
                raise ValueError(f'Parameter {label}: expected integer')
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    pass
            raise ValueError(
                f'Parameter {label}: expected integer, got {value!r}'
            )
        if base_type == 'number':
            if isinstance(value, bool):
                raise ValueError(f'Parameter {label}: expected number')
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    pass
            raise ValueError(
                f'Parameter {label}: expected number, got {value!r}'
            )
        if base_type == 'boolean':
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                low = value.lower()
                if low in ('true', '1', 'yes'):
                    return True
                if low in ('false', '0', 'no'):
                    return False
            raise ValueError(
                f'Parameter {label}: expected boolean, got {value!r}'
            )
        if base_type in ('date', 'datetime'):
            if not isinstance(value, str):
                raise ValueError(
                    f'Parameter {label}: expected {base_type} string, '
                    f'got {type(value).__name__}'
                )
            # Lightweight format validation; SQLite is permissive but we
            # want to catch obvious garbage early.
            if base_type == 'date':
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', value):
                    raise ValueError(
                        f'Parameter {label}: expected YYYY-MM-DD, got {value!r}'
                    )
            else:
                if not re.match(
                    r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?', value
                ):
                    raise ValueError(
                        f'Parameter {label}: expected ISO datetime, '
                        f'got {value!r}'
                    )
            return value
        raise ValueError(f'Unsupported parameter type: {base_type}')
