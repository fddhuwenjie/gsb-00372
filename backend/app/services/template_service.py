"""
Reusable, parameterised query templates.

A template wraps a fixed query AST plus a set of declared parameters. The
AST references parameters by name (via the ``param`` key on condition
leaves, and ``limitParam``/``offsetParam`` for pagination). Instantiation
only substitutes *values*; it never alters the AST structure (tables,
joins, columns or operators). The backend remains the single source of
truth for SQL generation and read-only execution semantics.

Templates carry a ``template_version`` so that future schema changes can
be migrated, and each parameter may optionally bind to a table instance
id + column name so that schema refreshes can produce locatable migration
errors when the referenced field is deleted or its type changes.
"""
from copy import deepcopy

from sqlalchemy import inspect

from app.database import db
from app.services.security_service import SecurityService
from app.services.sql_generator import SQLGenerator

CURRENT_TEMPLATE_VERSION = 1


class TemplateValidationError(ValueError):
    """Raised when a template definition or instantiation is invalid."""


class TemplateMigrationError(TemplateValidationError):
    """Raised when a template's references are stale against the schema."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(errors))


class TemplateService:
    @staticmethod
    def validate_template(template):
        """
        Validate a template object: version, parameters and the underlying
        query AST. Returns the normalised template.
        """
        if not isinstance(template, dict):
            raise TemplateValidationError('Template must be an object')

        version = template.get('template_version', CURRENT_TEMPLATE_VERSION)
        if not isinstance(version, int) or version < 1:
            raise TemplateValidationError(
                f'Unsupported template_version: {version}'
            )
        if version > CURRENT_TEMPLATE_VERSION:
            raise TemplateValidationError(
                f'Template version {version} is newer than supported '
                f'version {CURRENT_TEMPLATE_VERSION}'
            )

        name = template.get('name')
        if not name or not isinstance(name, str):
            raise TemplateValidationError('Template name is required')

        parameters = template.get('parameters') or []
        if not isinstance(parameters, list):
            raise TemplateValidationError('parameters must be a list')

        declared = {}
        for param in parameters:
            SecurityService.validate_param_declaration(param)
            pname = param['name']
            if pname in declared:
                raise TemplateValidationError(
                    f'Duplicate parameter name: {pname}'
                )
            declared[pname] = param

        query = template.get('queryStructure')
        if not isinstance(query, dict):
            raise TemplateValidationError(
                'Template must include a queryStructure'
            )

        # Validate the AST; also ensure every param reference resolves to
        # a declared parameter.
        SecurityService.validate_ast_structure(query)
        TemplateService._check_param_references(query, declared)

        return {
            'template_version': version,
            'name': name,
            'description': template.get('description', ''),
            'parameters': parameters,
            'queryStructure': deepcopy(query),
        }

    @staticmethod
    def _check_param_references(query, declared):
        """Walk the AST and ensure every param/limitParam/offsetParam is
        declared, and that list-typed params are only used with IN/NOT IN.
        """
        referenced = set()

        def walk(node):
            if isinstance(node, dict):
                if 'param' in node and node['param']:
                    pname = node['param']
                    if pname not in declared:
                        raise TemplateValidationError(
                            f'Condition references undeclared parameter: '
                            f'{pname}'
                        )
                    referenced.add(pname)
                    cmp = node.get('cmp')
                    ptype = declared[pname]['type']
                    is_list = ptype.endswith('_list')
                    if is_list and cmp not in ('IN', 'NOT IN'):
                        raise TemplateValidationError(
                            f'List parameter {pname} can only be used '
                            f'with IN/NOT IN (found {cmp})'
                        )
                    if not is_list and cmp in ('IN', 'NOT IN'):
                        raise TemplateValidationError(
                            f'Scalar parameter {pname} used with {cmp}; '
                            f'use a *_list parameter type'
                        )
                for key in ('limitParam', 'offsetParam'):
                    if node.get(key):
                        pname = node[key]
                        if pname not in declared:
                            raise TemplateValidationError(
                                f'{key} references undeclared parameter: '
                                f'{pname}'
                            )
                        referenced.add(pname)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(query)

        # Required parameters need not be referenced to be useful, but
        # declared parameters that are never referenced are almost always
        # a mistake. We warn-by-error to keep templates honest.
        unused = set(declared) - referenced
        if unused:
            raise TemplateValidationError(
                f'Declared parameters not used in query: {sorted(unused)}'
            )

    @staticmethod
    def check_schema(template):
        """
        Verify that every table instance and (optionally) bound column
        still exists in the current database schema and that the column
        type is compatible with the declared parameter type.

        Raises TemplateMigrationError with locatable messages on mismatch.
        """
        errors = []
        query = template['queryStructure']
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())

        table_instances = {t['id']: t for t in query.get('tables', [])}

        # 1. Tables still exist
        for tid, table in table_instances.items():
            if table['tableName'] not in existing_tables:
                errors.append(
                    f'Table instance "{tid}" references missing table '
                    f'"{table["tableName"]}"'
                )

        # 2. Columns referenced by selected fields / joins / conditions
        #    still exist.
        schema_cols = {}
        for tname in existing_tables:
            schema_cols[tname] = {
                c['name']: str(c['type']).upper()
                for c in inspector.get_columns(tname)
            }

        def check_column(table_id, column_name, location):
            table = table_instances.get(table_id)
            if not table:
                errors.append(
                    f'{location} references unknown table instance '
                    f'"{table_id}"'
                )
                return
            cols = schema_cols.get(table['tableName'], {})
            if column_name not in cols and column_name != '*':
                errors.append(
                    f'{location}: column "{column_name}" no longer exists '
                    f'on table "{table["tableName"]}" (instance "{table_id}")'
                )

        for field in query.get('selectedFields', []):
            check_column(
                field['tableId'], field['columnName'],
                f'selectedField alias={field.get("alias") or field["columnName"]}'
            )
        for join in query.get('joins', []) or []:
            if join.get('type') == 'CROSS':
                continue
            check_column(
                join['leftTableId'], join['leftColumn'],
                f'join "{join["id"]}" left'
            )
            check_column(
                join['rightTableId'], join['rightColumn'],
                f'join "{join["id"]}" right'
            )
        for order in query.get('orderBy', []) or []:
            check_column(
                order['tableId'], order['columnName'], 'orderBy'
            )

        def walk_conditions(node):
            if not isinstance(node, dict):
                return
            if 'children' in node:
                for child in node.get('children', []):
                    walk_conditions(child)
            if 'child' in node:
                walk_conditions(node['child'])
            if 'tableId' in node and 'columnName' in node:
                check_column(
                    node['tableId'], node['columnName'],
                    f'condition parameter={node.get("param", "<inline>")}'
                )

        walk_conditions(query.get('where'))
        walk_conditions(query.get('having'))

        # 3. Parameter-to-column bindings: type compatibility.
        for param in template.get('parameters', []):
            if param.get('tableId') and param.get('columnName'):
                tid = param['tableId']
                cname = param['columnName']
                table = table_instances.get(tid)
                if table and table['tableName'] in schema_cols:
                    col_type = schema_cols[table['tableName']].get(cname, '')
                    if cname not in schema_cols[table['tableName']]:
                        errors.append(
                            f'Parameter "{param["name"]}" binds to missing '
                            f'column "{cname}" on "{table["tableName"]}"'
                        )
                        continue
                    if not TemplateService._type_compatible(
                        param['type'], col_type
                    ):
                        errors.append(
                            f'Parameter "{param["name"]}" declared type '
                            f'{param["type"]} is incompatible with column '
                            f'"{table["tableName"]}"."{cname}" ({col_type})'
                        )

        if errors:
            raise TemplateMigrationError(errors)
        return True

    @staticmethod
    def _type_compatible(param_type, column_type):
        base = param_type[:-5] if param_type.endswith('_list') else param_type
        ct = column_type.upper()
        if base in ('string',):
            return True  # SQLite is dynamically typed
        if base in ('integer',):
            return any(k in ct for k in ('INT',))
        if base in ('number',):
            return any(k in ct for k in ('NUM', 'DECIMAL', 'REAL', 'FLOAT', 'DOUBLE', 'INT'))
        if base in ('boolean',):
            return 'BOOL' in ct
        if base in ('date', 'datetime'):
            return any(k in ct for k in ('DATE', 'TIME'))
        return True

    @staticmethod
    def instantiate(template, values):
        """
        Build a concrete (sql, params, query_structure) from a template and
        a dict of runtime parameter values. Only values are substituted;
        the AST structure is copied unchanged.
        """
        normalised = TemplateService.validate_template(template)
        TemplateService.check_schema(normalised)

        declared = {p['name']: p for p in normalised['parameters']}
        resolved = {}
        for name, decl in declared.items():
            if name in (values or {}):
                raw = values[name]
            elif decl.get('required'):
                raise TemplateValidationError(
                    f'Missing required parameter: {name}'
                )
            elif 'default' in decl:
                raw = decl['default']
            elif decl['type'].endswith('_list'):
                raw = []
            else:
                # No default and not required -> treat as NULL
                raw = None
            try:
                resolved[name] = SecurityService.coerce_param_value(
                    raw, decl['type'], name
                )
            except ValueError as exc:
                raise TemplateValidationError(str(exc)) from exc

        # The query AST already carries param references; pass the
        # resolved values straight to the generator, which binds them as
        # named parameters without modifying the structure.
        query = deepcopy(normalised['queryStructure'])
        generator = SQLGenerator(query, param_values=resolved)
        sql = generator.generate()
        params = generator.get_params()
        return {
            'sql': sql,
            'params': params,
            'queryStructure': query,
            'resolvedParameters': resolved,
        }

    @staticmethod
    def describe_parameters(template):
        """Return parameter metadata for the frontend form."""
        result = []
        for param in template.get('parameters', []):
            result.append({
                'name': param['name'],
                'type': param['type'],
                'label': param.get('label', param['name']),
                'required': bool(param.get('required', False)),
                'default': param.get('default'),
                'usage': param.get('usage', 'filter'),
                'tableId': param.get('tableId'),
                'columnName': param.get('columnName'),
                'options': param.get('options'),
                'help': param.get('help'),
            })
        return result
