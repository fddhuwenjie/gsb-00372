"""Parameterized query template engine.

A template = unified query AST + typed parameter declarations. Parameters
reference condition clauses by their stable clause id (or limit/offset) and
are the *only* thing instantiation may change: values are substituted into
the AST and then flow through the normal generator as bound parameters. The
SQL structure can never be spliced from the outside.
"""
from copy import deepcopy
from datetime import date, datetime


class TemplateError(Exception):
    """Locatable template error. ``issues`` is a list of dicts, each with a
    ``path`` pointing at the exact AST/parameter location, a machine-readable
    ``code`` and a human-readable ``message``."""

    def __init__(self, message, issues=None, status=400):
        super().__init__(message)
        self.issues = issues or []
        self.status = status


MISSING = object()


class TemplateService:
    PARAM_TYPES = {
        'string', 'integer', 'number', 'boolean', 'date', 'datetime',
        'string[]', 'integer[]', 'number[]',
    }
    TARGET_KINDS = {'where', 'having', 'limit', 'offset'}
    NULL_OPERATORS = {'IS NULL', 'IS NOT NULL'}
    SUBQUERY_OPERATORS = {'EXISTS', 'NOT EXISTS'}
    LIST_OPERATORS = {'IN', 'NOT IN'}

    # normalized column-type groups a parameter base type may bind to
    _PARAM_COLUMN_COMPAT = {
        'string': {'string'},
        'integer': {'integer', 'number'},
        'number': {'integer', 'number'},
        'boolean': {'boolean', 'integer'},
        'date': {'date'},
        'datetime': {'date'},
    }

    # ------------------------------------------------------------------
    # AST condition-tree helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _walk_clauses(node, path):
        """Yield (clause_node, locatable_path) for every clause in a tree."""
        if not isinstance(node, dict):
            return
        if 'op' in node and 'children' in node:
            for index, child in enumerate(node.get('children') or []):
                yield from TemplateService._walk_clauses(child, f'{path}.children[{index}]')
        elif 'cmp' in node:
            yield node, f"{path} (clause '{node.get('id', '?')}')"

    # ------------------------------------------------------------------
    # Type coercion (values only; never structure)
    # ------------------------------------------------------------------
    @staticmethod
    def _base_type(param_type):
        return param_type[:-2] if param_type.endswith('[]') else param_type

    @staticmethod
    def coerce_value(param, raw):
        """Coerce/validate a raw input value against the declared type.
        Returns the coerced value or raises TemplateError naming the parameter."""
        name = param.get('name', '?')
        ptype = param.get('type')

        if raw is None:
            # None is a valid *value* for filter targets: the generator maps
            # it to IS NULL / IS NOT NULL for = / != comparisons.
            if param.get('target', {}).get('kind') in ('where', 'having'):
                return None
            raise TemplateError(f"Parameter '{name}' must not be null")

        try:
            if ptype.endswith('[]'):
                if not isinstance(raw, list):
                    raise ValueError('expected a list')
                item_type = ptype[:-2]
                return [TemplateService._coerce_scalar(item_type, item) for item in raw]
            return TemplateService._coerce_scalar(ptype, raw)
        except (TypeError, ValueError) as e:
            raise TemplateError(
                f"Parameter '{name}': invalid value {raw!r} for type {ptype} ({e})"
            )

    @staticmethod
    def _coerce_scalar(ptype, value):
        if ptype == 'string':
            if not isinstance(value, str):
                raise ValueError(f'expected string, got {type(value).__name__}')
            return value
        if ptype == 'integer':
            if isinstance(value, bool):
                raise ValueError('expected integer, got boolean')
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.strip().lstrip('-').isdigit():
                return int(value.strip())
            raise ValueError(f'expected integer, got {value!r}')
        if ptype == 'number':
            if isinstance(value, bool):
                raise ValueError('expected number, got boolean')
            if isinstance(value, (int, float)):
                return value
            if isinstance(value, str):
                return float(value.strip())
            raise ValueError(f'expected number, got {value!r}')
        if ptype == 'boolean':
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in ('true', 'false'):
                return value.strip().lower() == 'true'
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            raise ValueError(f'expected boolean, got {value!r}')
        if ptype == 'date':
            if not isinstance(value, str):
                raise ValueError(f'expected ISO date string, got {type(value).__name__}')
            return date.fromisoformat(value.strip()).isoformat()
        if ptype == 'datetime':
            if not isinstance(value, str):
                raise ValueError(f'expected ISO datetime string, got {type(value).__name__}')
            return datetime.fromisoformat(value.strip()).isoformat(sep=' ')
        raise ValueError(f'unknown parameter type {ptype!r}')

    # ------------------------------------------------------------------
    # Definition validation (authoring time)
    # ------------------------------------------------------------------
    @classmethod
    def validate_definition(cls, parameters, query_structure):
        issues = []
        parameters = parameters or []

        if not isinstance(parameters, list):
            raise TemplateError('parameters must be a list')

        if not query_structure or not query_structure.get('tables'):
            issues.append({
                'code': 'NO_TABLES', 'path': 'query.tables',
                'message': 'Template query must contain at least one table instance',
            })

        seen_ids, seen_names = set(), set()
        clause_paths = {}
        for kind in ('where', 'having'):
            tree = (query_structure or {}).get(kind)
            for node, path in cls._walk_clauses(tree, f'query.{kind}'):
                clause_paths[node.get('id')] = (kind, node, path)

        for index, param in enumerate(parameters):
            path = f'parameters[{index}]'
            pid = param.get('id')
            pname = param.get('name')
            ptype = param.get('type')
            label = f"{path} ('{pname}')" if pname else path

            if not pid:
                issues.append({'code': 'PARAM_ID_MISSING', 'path': path,
                               'message': 'Parameter requires a stable id'})
            elif pid in seen_ids:
                issues.append({'code': 'PARAM_ID_DUPLICATE', 'path': label,
                               'message': f"Duplicate parameter id '{pid}'"})
            seen_ids.add(pid)

            if not pname:
                issues.append({'code': 'PARAM_NAME_MISSING', 'path': path,
                               'message': 'Parameter requires a name'})
            elif pname in seen_names:
                issues.append({'code': 'PARAM_NAME_DUPLICATE', 'path': label,
                               'message': f"Duplicate parameter name '{pname}'"})
            seen_names.add(pname)

            if ptype not in cls.PARAM_TYPES:
                issues.append({'code': 'PARAM_TYPE_INVALID', 'path': label,
                               'message': f"Unknown parameter type '{ptype}'",
                               'expected': sorted(cls.PARAM_TYPES), 'actual': ptype})
                continue

            if not param.get('required', False) and 'default' not in param:
                issues.append({'code': 'PARAM_DEFAULT_MISSING', 'path': label,
                               'message': 'Optional parameters must declare a default value '
                                          '(instantiation never alters query structure)'})

            if 'default' in param:
                try:
                    cls.coerce_value({**param, 'target': param.get('target') or {}},
                                     param.get('default'))
                except TemplateError as e:
                    issues.append({'code': 'PARAM_DEFAULT_INVALID', 'path': label,
                                   'message': str(e)})

            target = param.get('target')
            if not isinstance(target, dict) or target.get('kind') not in cls.TARGET_KINDS:
                issues.append({'code': 'PARAM_TARGET_INVALID', 'path': label,
                               'message': "Parameter target must be one of 'where', 'having', 'limit', 'offset'"})
                continue

            kind = target['kind']
            if kind in ('limit', 'offset'):
                if ptype != 'integer':
                    issues.append({'code': 'PARAM_TYPE_MISMATCH', 'path': label,
                                   'message': f"Parameters bound to {kind} must be of type 'integer'",
                                   'expected': 'integer', 'actual': ptype})
                continue

            node_id = target.get('nodeId')
            found = clause_paths.get(node_id)
            if not found:
                issues.append({'code': 'PARAM_TARGET_MISSING', 'path': label,
                               'message': f"Target clause '{node_id}' not found in query.{kind}",
                               'target': node_id})
                continue

            _, node, node_path = found
            cmp = node.get('cmp')
            if cmp in cls.NULL_OPERATORS:
                issues.append({'code': 'PARAM_TARGET_NULLOP', 'path': f'{label} -> {node_path}',
                               'message': f"Clause uses {cmp} and takes no value"})
            elif cmp in cls.SUBQUERY_OPERATORS or 'subquery' in node:
                issues.append({'code': 'PARAM_TARGET_SUBQUERY', 'path': f'{label} -> {node_path}',
                               'message': 'Subquery clauses cannot be parameterized'})
            elif cmp in cls.LIST_OPERATORS and not ptype.endswith('[]'):
                issues.append({'code': 'PARAM_TYPE_MISMATCH', 'path': f'{label} -> {node_path}',
                               'message': f"{cmp} requires a list parameter type",
                               'expected': 'list type (e.g. string[])', 'actual': ptype})
            elif cmp == 'LIKE' and ptype != 'string':
                issues.append({'code': 'PARAM_TYPE_MISMATCH', 'path': f'{label} -> {node_path}',
                               'message': 'LIKE requires a string parameter',
                               'expected': 'string', 'actual': ptype})

        if issues:
            raise TemplateError('Invalid template definition', issues=issues)
        return True

    # ------------------------------------------------------------------
    # Schema validation (migration safety)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_column_type(type_str):
        base = (type_str or '').split('(')[0].strip().upper()
        if base in ('INT', 'INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT'):
            return 'integer'
        if base in ('NUMERIC', 'DECIMAL', 'REAL', 'FLOAT', 'DOUBLE'):
            return 'number'
        if base in ('VARCHAR', 'CHAR', 'TEXT', 'STRING', 'CLOB'):
            return 'string'
        if base in ('DATE', 'DATETIME', 'TIMESTAMP'):
            return 'date'
        if base in ('BOOLEAN', 'BOOL'):
            return 'boolean'
        return 'other'

    @classmethod
    def validate_against_schema(cls, parameters, query_structure, metadata):
        """Check every table-instance/column reference against current schema
        metadata. Returns a list of locatable migration issues (empty = ok)."""
        issues = []
        meta_by_name = {t['name']: t for t in metadata}
        tables = (query_structure or {}).get('tables') or []
        tables_by_id = {t.get('id'): t for t in tables}

        column_cache = {}
        for index, table in enumerate(tables):
            tname = table.get('tableName')
            meta = meta_by_name.get(tname)
            if not meta:
                issues.append({
                    'code': 'TABLE_MISSING',
                    'path': f"query.tables[{index}] (instance '{table.get('id')}', alias '{table.get('alias')}')",
                    'table': tname,
                    'message': f"Table '{tname}' no longer exists in the schema",
                })
                column_cache[table.get('id')] = None
            else:
                column_cache[table.get('id')] = {c['name']: c for c in meta['columns']}

        def check_column(table_id, column_name, path):
            table = tables_by_id.get(table_id) or {}
            columns = column_cache.get(table_id)
            if columns is None:
                return None  # table-level issue already reported
            col = columns.get(column_name)
            if not col:
                issues.append({
                    'code': 'COLUMN_MISSING', 'path': path,
                    'table': table.get('tableName'), 'tableAlias': table.get('alias'),
                    'column': column_name,
                    'message': f"Column '{column_name}' no longer exists on table "
                               f"'{table.get('tableName')}' (instance alias '{table.get('alias')}')",
                })
                return None
            return col

        for i, field in enumerate((query_structure or {}).get('selectedFields') or []):
            check_column(field.get('tableId'), field.get('columnName'),
                         f'query.selectedFields[{i}]')

        for i, agg in enumerate((query_structure or {}).get('aggregations') or []):
            check_column(agg.get('tableId'), agg.get('columnName'), f'query.aggregations[{i}]')

        for i, join in enumerate((query_structure or {}).get('joins') or []):
            if join.get('type') == 'CROSS':
                continue  # CROSS joins carry no column references
            check_column(join.get('leftTableId'), join.get('leftColumn'),
                         f"query.joins[{i}] (join '{join.get('id')}', left side)")
            check_column(join.get('rightTableId'), join.get('rightColumn'),
                         f"query.joins[{i}] (join '{join.get('id')}', right side)")

        params_by_node = {}
        for index, param in enumerate(parameters or []):
            target = param.get('target') or {}
            if target.get('kind') in ('where', 'having') and target.get('nodeId'):
                params_by_node[target['nodeId']] = (index, param)

        for kind in ('where', 'having'):
            for node, path in cls._walk_clauses((query_structure or {}).get(kind), f'query.{kind}'):
                col = check_column(node.get('tableId'), node.get('columnName'), path)
                if not col:
                    continue
                binding = params_by_node.get(node.get('id'))
                if not binding:
                    continue
                index, param = binding
                base = cls._base_type(param.get('type', ''))
                allowed = cls._PARAM_COLUMN_COMPAT.get(base, set())
                actual_group = cls._normalize_column_type(col.get('type'))
                if actual_group not in allowed:
                    issues.append({
                        'code': 'COLUMN_TYPE_CHANGED',
                        'path': f"parameters[{index}] ('{param.get('name')}') -> {path}",
                        'parameter': param.get('name'),
                        'tableAlias': (tables_by_id.get(node.get('tableId')) or {}).get('alias'),
                        'column': node.get('columnName'),
                        'expected': f"{param.get('type')} (column groups: {sorted(allowed)})",
                        'actual': col.get('type'),
                        'message': f"Type of column '{node.get('columnName')}' changed to "
                                   f"'{col.get('type')}', incompatible with parameter "
                                   f"'{param.get('name')}' of type '{param.get('type')}'",
                    })

        return issues

    # ------------------------------------------------------------------
    # Instantiation (values only)
    # ------------------------------------------------------------------
    @classmethod
    def instantiate(cls, parameters, query_structure, values):
        """Return a plain QueryStructure with parameter values substituted.
        Only clause values / limit / offset are touched; the AST shape is
        preserved exactly."""
        values = dict(values or {})
        known = {p.get('name') for p in parameters or []}
        unknown = sorted(set(values) - known)
        if unknown:
            raise TemplateError(f"Unknown parameter(s): {', '.join(unknown)}")

        ast = deepcopy(query_structure)

        for index, param in enumerate(parameters or []):
            label = f"parameters[{index}] ('{param.get('name')}')"
            raw = values.get(param['name'], param.get('default', MISSING))
            if raw is MISSING:
                raise TemplateError(
                    f"Missing required parameter: '{param['name']}'",
                    issues=[{'code': 'PARAM_VALUE_MISSING', 'path': label,
                             'parameter': param['name'],
                             'message': f"Parameter '{param['name']}' is required and has no default"}],
                )
            value = cls.coerce_value(param, raw)

            target = param['target']
            kind = target['kind']
            if kind == 'limit':
                ast['limit'] = value
            elif kind == 'offset':
                ast['offset'] = value
            else:
                node = cls._find_clause(ast.get(kind), target['nodeId'])
                if node is None:
                    raise TemplateError(
                        f"Target clause '{target['nodeId']}' not found in query.{kind}",
                        issues=[{'code': 'PARAM_TARGET_MISSING',
                                 'path': f'{label} -> query.{kind}',
                                 'target': target['nodeId'],
                                 'message': f"Target clause '{target['nodeId']}' not found"}],
                    )
                node['value'] = value

        return ast

    @staticmethod
    def _find_clause(tree, node_id):
        if not isinstance(tree, dict):
            return None
        if 'op' in tree and 'children' in tree:
            for child in tree.get('children') or []:
                found = TemplateService._find_clause(child, node_id)
                if found is not None:
                    return found
            return None
        if tree.get('id') == node_id and 'cmp' in tree:
            return tree
        return None
