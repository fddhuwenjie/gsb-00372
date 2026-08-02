"""Reusable, parameterized query templates.

A template is a normal query AST (the same unified structure the SQLGenerator
consumes) in which selected *values* -- filter values, pagination bounds and
time-window bounds -- are replaced by typed parameter references of the form
``{"$param": "<name>"}``. The template also declares those parameters with a
type, an optional default and a required flag.

Design guarantees (aligned with the single-SQL-source and read-only boundary
from the previous round):

  * Instantiation only ever substitutes parameter *values*. Placeholders are
    allowed exclusively in filter ``value`` slots and in ``limit`` / ``offset``.
    A placeholder anywhere structural (table/column name, join type, operator,
    aggregation, alias, ...) is rejected at declaration time, so a template can
    never be used to splice SQL structure.
  * References bind to the stable table-instance id + column name already used
    by the AST, so they survive save, share and schema refreshes.
  * ``check_schema`` compares every field reference against live metadata and
    raises a *locatable* migration error when a field was removed or its type
    changed incompatibly with a bound parameter.
"""
import re
from copy import deepcopy

from app.services.security_service import SecurityService

PLACEHOLDER_KEY = '$param'

PARAM_TYPES = {'integer', 'number', 'string', 'boolean', 'date', 'list'}
# Slots in which a parameter placeholder is permitted (value-only).
VALUE_SLOTS = {'value', 'limit', 'offset'}

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$')
_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


class TemplateError(ValueError):
    """Base error for template declaration / instantiation problems."""


class MissingParameterError(TemplateError):
    pass


class ParameterTypeError(TemplateError):
    pass


class TemplateStructureError(TemplateError):
    """A placeholder appears in a position that would splice SQL structure."""


class SchemaMigrationError(TemplateError):
    """A referenced field no longer matches the live database schema. Carries
    enough context (table instance, table, column) to locate the problem."""

    def __init__(self, message, references=None):
        super().__init__(message)
        self.references = references or []


def is_placeholder(obj):
    return (
        isinstance(obj, dict)
        and len(obj) == 1
        and PLACEHOLDER_KEY in obj
        and isinstance(obj[PLACEHOLDER_KEY], str)
    )


# --- schema type categories (lenient, SQLite-oriented) ---------------------
def _column_category(sql_type):
    t = (sql_type or '').upper()
    if 'INT' in t:
        return 'integer'
    if any(k in t for k in ('CHAR', 'CLOB', 'TEXT')):
        return 'string'
    if any(k in t for k in ('REAL', 'FLOA', 'DOUB', 'NUM', 'DEC')):
        return 'number'
    if 'BOOL' in t:
        return 'boolean'
    if 'DATE' in t or 'TIME' in t:
        return 'date'
    return 'any'


def _param_category(param_type):
    # integer values are acceptable wherever a number is; treat as numeric family
    if param_type in ('integer', 'number'):
        return 'number'
    if param_type == 'list':
        return 'any'
    return param_type


def _categories_compatible(param_type, column_type):
    col = _column_category(column_type)
    if col == 'any':
        return True
    par = _param_category(param_type)
    if par == 'any':
        return True
    # numbers cover integer columns and vice versa; dates stored as text are ok
    if par == 'number':
        return col in ('number', 'integer')
    if par == 'date':
        return col in ('date', 'string')
    if par == 'string':
        return col in ('string', 'date', 'any')
    if par == 'boolean':
        return col in ('boolean', 'integer')
    return par == col


class TemplateService:
    # ---------------------------------------------------------------- declare
    @staticmethod
    def validate_parameter_declaration(param):
        name = param.get('name')
        if not name or not _NAME_RE.match(name):
            raise TemplateError(f'Invalid parameter name: {name!r}')
        ptype = param.get('type')
        if ptype not in PARAM_TYPES:
            raise TemplateError(f'Invalid parameter type for {name!r}: {ptype!r}')
        if ptype == 'list':
            item_type = param.get('itemType', 'string')
            if item_type not in PARAM_TYPES or item_type == 'list':
                raise TemplateError(
                    f'Invalid list itemType for {name!r}: {item_type!r}'
                )
        if 'default' in param and param['default'] is not None:
            # Defaults must themselves satisfy the declared type.
            TemplateService._coerce_and_check(name, param, param['default'])
        return True

    @staticmethod
    def validate_template(template):
        """Validate a template's parameter declarations and that every
        placeholder sits in a value-only slot referencing a declared param."""
        params = template.get('parameters') or []
        names = set()
        for p in params:
            TemplateService.validate_parameter_declaration(p)
            if p['name'] in names:
                raise TemplateError(f'Duplicate parameter name: {p["name"]!r}')
            names.add(p['name'])

        qs = template.get('queryStructure')
        if not isinstance(qs, dict):
            raise TemplateError('Template requires a queryStructure')

        referenced = set()
        TemplateService._scan_placeholders(qs, None, referenced, [])

        unknown = referenced - names
        if unknown:
            raise TemplateError(
                f'Template references undeclared parameter(s): {", ".join(sorted(unknown))}'
            )
        return True

    @staticmethod
    def _scan_placeholders(obj, parent_key, referenced, loc):
        if is_placeholder(obj):
            if parent_key not in VALUE_SLOTS:
                raise TemplateStructureError(
                    f'Parameter placeholder is only allowed in filter values, '
                    f'limit or offset; found in structural position '
                    f'"{parent_key}" at {"/".join(loc) or "root"}'
                )
            referenced.add(obj[PLACEHOLDER_KEY])
            return
        if isinstance(obj, dict):
            for key, val in obj.items():
                TemplateService._scan_placeholders(val, key, referenced, loc + [key])
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                # List items inherit their container key (e.g. a value list).
                TemplateService._scan_placeholders(item, parent_key, referenced, loc + [str(i)])

    # ------------------------------------------------------------ auto-derive
    @staticmethod
    def parameterize(query_structure, specs):
        """Turn a concrete query AST into a template by replacing the values of
        chosen filter leaves / pagination bounds with placeholders.

        ``specs`` is a list of ``{name, type, target, ...}`` where ``target`` is
        one of ``{"kind": "filter", "clauseId": <id>}`` or
        ``{"kind": "limit"}`` / ``{"kind": "offset"}``. Only values are touched.
        """
        qs = deepcopy(query_structure)
        parameters = []
        for spec in specs:
            name = spec['name']
            ptype = spec['type']
            target = spec.get('target', {})
            kind = target.get('kind')
            decl = {'name': name, 'type': ptype}
            for opt in ('required', 'default', 'label', 'itemType'):
                if opt in spec:
                    decl[opt] = spec[opt]
            parameters.append(decl)

            if kind == 'filter':
                clause_id = target.get('clauseId')
                if not TemplateService._set_filter_placeholder(qs, clause_id, name):
                    raise TemplateError(f'Filter clause not found: {clause_id}')
            elif kind == 'limit':
                qs['limit'] = {PLACEHOLDER_KEY: name}
            elif kind == 'offset':
                qs['offset'] = {PLACEHOLDER_KEY: name}
            else:
                raise TemplateError(f'Unknown parameterize target kind: {kind!r}')

        template = {'queryStructure': qs, 'parameters': parameters}
        TemplateService.validate_template(template)
        return template

    @staticmethod
    def _set_filter_placeholder(qs, clause_id, name):
        found = [False]

        def walk(node):
            if not isinstance(node, dict):
                return
            if node.get('id') == clause_id and 'cmp' in node:
                node['value'] = {PLACEHOLDER_KEY: name}
                found[0] = True
                return
            for child in node.get('children', []) or []:
                walk(child)

        for key in ('where', 'having'):
            if qs.get(key):
                walk(qs[key])
        for cte in qs.get('ctes', []) or []:
            if cte.get('queryStructure'):
                TemplateService._set_filter_placeholder(cte['queryStructure'], clause_id, name)
        return found[0]

    # -------------------------------------------------------------- resolve
    @staticmethod
    def resolve_parameters(template, values):
        """Resolve declared parameters against supplied values, applying
        defaults and required constraints, and validating types."""
        params = template.get('parameters') or []
        values = values or {}
        resolved = {}
        for p in params:
            name = p['name']
            if name in values and values[name] is not None:
                raw = values[name]
            elif p.get('default') is not None:
                raw = p['default']
            elif p.get('required'):
                raise MissingParameterError(f'Missing required parameter: {name}')
            else:
                # Optional with no value/default: only valid if it has a default.
                raise MissingParameterError(
                    f'Parameter {name} has no value and no default'
                )
            resolved[name] = TemplateService._coerce_and_check(name, p, raw)
        return resolved

    @staticmethod
    def _coerce_and_check(name, param, value):
        ptype = param['type']
        if ptype == 'integer':
            if isinstance(value, bool) or not isinstance(value, int):
                raise ParameterTypeError(f'Parameter {name} must be an integer')
            return value
        if ptype == 'number':
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ParameterTypeError(f'Parameter {name} must be a number')
            return value
        if ptype == 'string':
            if not isinstance(value, str):
                raise ParameterTypeError(f'Parameter {name} must be a string')
            return value
        if ptype == 'boolean':
            if not isinstance(value, bool):
                raise ParameterTypeError(f'Parameter {name} must be a boolean')
            return value
        if ptype == 'date':
            if not isinstance(value, str) or not _DATE_RE.match(value):
                raise ParameterTypeError(
                    f'Parameter {name} must be a date string (YYYY-MM-DD)'
                )
            return value
        if ptype == 'list':
            if not isinstance(value, list):
                raise ParameterTypeError(f'Parameter {name} must be a list')
            item_type = param.get('itemType', 'string')
            item_decl = {'name': f'{name}[]', 'type': item_type}
            return [TemplateService._coerce_and_check(item_decl['name'], item_decl, v)
                    for v in value]
        raise ParameterTypeError(f'Unknown parameter type for {name}: {ptype}')

    # -------------------------------------------------------------- instantiate
    @staticmethod
    def instantiate(template, values, metadata=None):
        """Resolve values, optionally verify the schema, and return a concrete
        query AST (placeholders replaced by literal values) ready for the
        existing SQLGenerator / read-only executor."""
        TemplateService.validate_template(template)
        resolved = TemplateService.resolve_parameters(template, values)

        qs = deepcopy(template['queryStructure'])
        if metadata is not None:
            TemplateService.check_schema(qs, metadata, template.get('parameters') or [])

        bound = TemplateService._bind(qs, resolved)
        return bound

    @staticmethod
    def _bind(obj, resolved):
        """Deep-copy substitution that replaces placeholders with resolved
        values. Placeholders in structural positions were already rejected by
        validate_template, so this only ever fills in values."""
        if is_placeholder(obj):
            name = obj[PLACEHOLDER_KEY]
            if name not in resolved:
                raise MissingParameterError(f'Unresolved parameter: {name}')
            return deepcopy(resolved[name])
        if isinstance(obj, dict):
            return {k: TemplateService._bind(v, resolved) for k, v in obj.items()}
        if isinstance(obj, list):
            return [TemplateService._bind(v, resolved) for v in obj]
        return obj

    # -------------------------------------------------------------- schema
    @staticmethod
    def _build_metadata_index(metadata):
        idx = {}
        for table in metadata:
            cols = {c['name']: c.get('type', '') for c in table.get('columns', [])}
            idx[table['name']] = cols
        return idx

    @staticmethod
    def check_schema(query_structure, metadata, parameters):
        """Verify every field reference against live metadata. Collects all
        problems and raises a single SchemaMigrationError with locatable
        references, so a stale template reports exactly what to migrate."""
        idx = TemplateService._build_metadata_index(metadata)
        param_by_name = {p['name']: p for p in parameters}
        problems = []
        TemplateService._check_structure(query_structure, idx, param_by_name, problems)
        if problems:
            summary = '; '.join(p['message'] for p in problems)
            raise SchemaMigrationError(
                f'Template no longer matches the database schema: {summary}',
                references=problems,
            )
        return True

    @staticmethod
    def _check_structure(qs, idx, param_by_name, problems):
        tables = {t['id']: t for t in qs.get('tables', [])}

        def add(table_inst, column, reason):
            problems.append({
                'tableInstanceId': table_inst.get('id') if table_inst else None,
                'tableName': table_inst.get('tableName') if table_inst else None,
                'columnName': column,
                'reason': reason,
                'message': (
                    f'{reason}: '
                    f'{(table_inst or {}).get("tableName")}.{column} '
                    f'(instance {(table_inst or {}).get("id")})'
                ),
            })

        def check_ref(table_id, column, bound_param_type=None):
            table_inst = tables.get(table_id)
            if not table_inst:
                problems.append({
                    'tableInstanceId': table_id, 'tableName': None,
                    'columnName': column, 'reason': 'table_instance_missing',
                    'message': f'table_instance_missing: instance {table_id}',
                })
                return
            table_name = table_inst.get('tableName')
            cols = idx.get(table_name)
            if cols is None:
                add(table_inst, column, 'table_removed')
                return
            if column not in cols:
                add(table_inst, column, 'column_removed')
                return
            if bound_param_type and not _categories_compatible(bound_param_type, cols[column]):
                add(table_inst, column,
                    f'type_incompatible (column {cols[column]} vs parameter {bound_param_type})')

        # tables themselves
        for t in qs.get('tables', []):
            if t.get('tableName') not in idx:
                problems.append({
                    'tableInstanceId': t.get('id'), 'tableName': t.get('tableName'),
                    'columnName': None, 'reason': 'table_removed',
                    'message': f'table_removed: {t.get("tableName")} (instance {t.get("id")})',
                })

        for f in qs.get('selectedFields', []):
            check_ref(f['tableId'], f['columnName'])
        for a in qs.get('aggregations', []):
            check_ref(a['tableId'], a['columnName'])
        for o in qs.get('orderBy', []) or []:
            check_ref(o['tableId'], o['columnName'])
        for j in qs.get('joins', []):
            check_ref(j['leftTableId'], j.get('leftColumn')) if j.get('leftColumn') else None
            check_ref(j['rightTableId'], j.get('rightColumn')) if j.get('rightColumn') else None

        def walk_conditions(node):
            if not isinstance(node, dict):
                return
            if 'cmp' in node and 'columnName' in node:
                bound_type = None
                val = node.get('value')
                if is_placeholder(val):
                    p = param_by_name.get(val[PLACEHOLDER_KEY])
                    if p:
                        bound_type = p['type']
                check_ref(node['tableId'], node['columnName'], bound_type)
                if node.get('subquery'):
                    TemplateService._check_structure(node['subquery'], idx, param_by_name, problems)
            for child in node.get('children', []) or []:
                walk_conditions(child)

        for key in ('where', 'having'):
            if qs.get(key):
                walk_conditions(qs[key])
        for cte in qs.get('ctes', []) or []:
            if cte.get('queryStructure'):
                TemplateService._check_structure(cte['queryStructure'], idx, param_by_name, problems)
