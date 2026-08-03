from copy import deepcopy
from datetime import datetime, date
from app.services.metadata_service import MetadataService


PARAM_TYPES = {
    'string', 'integer', 'number', 'boolean', 'date',
    'string_list', 'integer_list', 'date_range',
}


class TemplateValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(errors))


class TemplateService:

    @staticmethod
    def validate_parameter_definition(param):
        errors = []
        name = param.get('name')
        if not name or not isinstance(name, str):
            errors.append('Parameter name is required and must be a string')
        elif not name.replace('_', '').isalnum() or not name[0].isalpha():
            errors.append(f'Parameter name must be alphanumeric/underscore starting with a letter: {name}')

        ptype = param.get('type')
        if ptype not in PARAM_TYPES:
            errors.append(f'Invalid parameter type for "{name}": {ptype}. Allowed: {sorted(PARAM_TYPES)}')

        if 'default' in param and param['default'] is not None:
            try:
                TemplateService._coerce_value(param['default'], ptype, name)
            except ValueError as e:
                errors.append(str(e))

        if param.get('required') and 'default' in param and param['default'] is not None:
            errors.append(f'Parameter "{name}" cannot be both required and have a default value')

        return errors

    @staticmethod
    def _coerce_value(value, ptype, param_name):
        if value is None:
            return None

        if ptype == 'string':
            if not isinstance(value, str):
                raise ValueError(f'Parameter "{param_name}" expects a string, got {type(value).__name__}')
            return value

        if ptype == 'integer':
            if isinstance(value, bool):
                raise ValueError(f'Parameter "{param_name}" expects an integer, got boolean')
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    raise ValueError(f'Parameter "{param_name}" expects an integer, got "{value}"')
            raise ValueError(f'Parameter "{param_name}" expects an integer')

        if ptype == 'number':
            if isinstance(value, bool):
                raise ValueError(f'Parameter "{param_name}" expects a number, got boolean')
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    raise ValueError(f'Parameter "{param_name}" expects a number, got "{value}"')
            raise ValueError(f'Parameter "{param_name}" expects a number')

        if ptype == 'boolean':
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                if value.lower() in ('true', '1', 'yes'):
                    return True
                if value.lower() in ('false', '0', 'no'):
                    return False
            raise ValueError(f'Parameter "{param_name}" expects a boolean')

        if ptype == 'date':
            if isinstance(value, date) and not isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, str):
                try:
                    parsed = datetime.strptime(value, '%Y-%m-%d').date()
                    return parsed.isoformat()
                except ValueError:
                    raise ValueError(f'Parameter "{param_name}" expects YYYY-MM-DD date, got "{value}"')
            raise ValueError(f'Parameter "{param_name}" expects a date string')

        if ptype == 'string_list':
            if not isinstance(value, list):
                raise ValueError(f'Parameter "{param_name}" expects a list of strings')
            result = []
            for i, item in enumerate(value):
                if not isinstance(item, str):
                    raise ValueError(f'Parameter "{param_name}"[{i}] expects a string')
                result.append(item)
            return result

        if ptype == 'integer_list':
            if not isinstance(value, list):
                raise ValueError(f'Parameter "{param_name}" expects a list of integers')
            result = []
            for i, item in enumerate(value):
                if isinstance(item, bool):
                    raise ValueError(f'Parameter "{param_name}"[{i}] expects an integer')
                if isinstance(item, int):
                    result.append(item)
                elif isinstance(item, str):
                    try:
                        result.append(int(item))
                    except ValueError:
                        raise ValueError(f'Parameter "{param_name}"[{i}] expects an integer')
                else:
                    raise ValueError(f'Parameter "{param_name}"[{i}] expects an integer')
            return result

        if ptype == 'date_range':
            if not isinstance(value, dict):
                raise ValueError(f'Parameter "{param_name}" expects an object with start and end')
            start = value.get('start')
            end = value.get('end')
            if not start or not end:
                raise ValueError(f'Parameter "{param_name}" requires both start and end dates')
            start_str = TemplateService._coerce_value(start, 'date', f'{param_name}.start')
            end_str = TemplateService._coerce_value(end, 'date', f'{param_name}.end')
            if start_str > end_str:
                raise ValueError(f'Parameter "{param_name}" start date must be before end date')
            return {'start': start_str, 'end': end_str}

        raise ValueError(f'Unknown parameter type: {ptype}')

    @staticmethod
    def extract_schema_refs(query_structure):
        refs = []
        seen = set()
        tables_by_id = {t['id']: t for t in query_structure.get('tables', [])}

        def add_ref(table_id, column_name, location):
            table = tables_by_id.get(table_id)
            if not table:
                return
            key = (table_id, column_name)
            if key in seen:
                return
            seen.add(key)
            refs.append({
                'tableId': table_id,
                'tableName': table['tableName'],
                'columnName': column_name,
                'location': location,
            })

        for field in query_structure.get('selectedFields', []):
            add_ref(field['tableId'], field['columnName'], 'selectedFields')

        for agg in query_structure.get('aggregations', []):
            add_ref(agg['tableId'], agg['columnName'], 'aggregations')

        for ob in query_structure.get('orderBy', []):
            add_ref(ob['tableId'], ob['columnName'], 'orderBy')

        for join in query_structure.get('joins', []):
            if join.get('type') != 'CROSS':
                add_ref(join['leftTableId'], join['leftColumn'], 'joins')
                add_ref(join['rightTableId'], join['rightColumn'], 'joins')

        def walk_conditions(node, clause):
            if not node:
                return
            if 'children' in node:
                for child in node.get('children', []):
                    walk_conditions(child, clause)
            elif 'columnName' in node:
                add_ref(node['tableId'], node['columnName'], clause)
                if 'subquery' in node:
                    sub_refs = TemplateService.extract_schema_refs(node['subquery'])
                    refs.extend(sub_refs)

        walk_conditions(query_structure.get('where'), 'where')
        walk_conditions(query_structure.get('having'), 'having')

        for cte in query_structure.get('ctes', []):
            cte_refs = TemplateService.extract_schema_refs(cte.get('queryStructure', {}))
            refs.extend(cte_refs)

        return refs

    @staticmethod
    def validate_against_schema(template):
        schema_refs = template.get('schema_refs', [])
        metadata = MetadataService.get_all_metadata()
        meta_by_table = {t['name']: t for t in metadata}

        errors = []
        for ref in schema_refs:
            table_name = ref['tableName']
            col_name = ref['columnName']
            loc = ref.get('location', 'unknown')
            table_meta = meta_by_table.get(table_name)

            if not table_meta:
                errors.append(
                    f'[Migration error] Table "{table_name}" (instance id: {ref["tableId"]}) '
                    f'referenced in {loc} no longer exists in the database schema'
                )
                continue

            col_meta = next((c for c in table_meta['columns'] if c['name'] == col_name), None)
            if not col_meta:
                errors.append(
                    f'[Migration error] Column "{col_name}" on table "{table_name}" '
                    f'(instance id: {ref["tableId"]}) referenced in {loc} has been deleted'
                )
                continue

        return errors

    @staticmethod
    def _walk_and_substitute(node, param_values, param_defs):
        if node is None:
            return None

        if isinstance(node, list):
            return [TemplateService._walk_and_substitute(item, param_values, param_defs) for item in node]

        if isinstance(node, dict):
            if '$param' in node and len(node) == 1:
                param_name = node['$param']
                if param_name not in param_values or param_values[param_name] is None:
                    raise ValueError(f'Unresolved or null parameter reference: {param_name}')
                return deepcopy(param_values[param_name])

            result = {}
            for key, value in node.items():
                result[key] = TemplateService._walk_and_substitute(value, param_values, param_defs)
            return result

        return node

    @staticmethod
    def _expand_date_ranges(query_structure, param_values):
        def walk_conditions(node):
            if not node:
                return None
            if 'children' in node:
                new_children = [walk_conditions(c) for c in node.get('children', [])]
                new_children = [c for c in new_children if c is not None]
                if not new_children:
                    return None
                return {**node, 'children': new_children}

            if 'cmp' in node and node['cmp'] == 'BETWEEN':
                param_name = node.get('paramRef')
                if param_name and param_name in param_values:
                    dr = param_values[param_name]
                    if isinstance(dr, dict) and 'start' in dr and 'end' in dr:
                        return {
                            'op': 'AND',
                            'id': f'{node.get("id", "c")}_range',
                            'children': [
                                {
                                    'id': f'{node.get("id", "c")}_start',
                                    'tableId': node['tableId'],
                                    'columnName': node['columnName'],
                                    'cmp': '>=',
                                    'value': dr['start'],
                                },
                                {
                                    'id': f'{node.get("id", "c")}_end',
                                    'tableId': node['tableId'],
                                    'columnName': node['columnName'],
                                    'cmp': '<=',
                                    'value': dr['end'],
                                },
                            ],
                        }
                return None

            return node

        qs = deepcopy(query_structure)
        if qs.get('where'):
            qs['where'] = walk_conditions(qs['where'])
        if qs.get('having'):
            qs['having'] = walk_conditions(qs['having'])

        if isinstance(qs.get('limit'), dict) and '$param' in qs['limit']:
            pname = qs['limit']['$param']
            qs['limit'] = param_values.get(pname, 100)
        if isinstance(qs.get('offset'), dict) and '$param' in qs['offset']:
            pname = qs['offset']['$param']
            qs['offset'] = param_values.get(pname, 0)

        return qs

    @staticmethod
    def instantiate(template, param_values):
        parameters = template.get('parameters', [])
        param_defs = {p['name']: p for p in parameters}

        errors = []
        resolved = {}

        for param in parameters:
            name = param['name']
            ptype = param['type']
            required = param.get('required', False)
            has_default = 'default' in param and param['default'] is not None

            if name in param_values and param_values[name] is not None:
                try:
                    resolved[name] = TemplateService._coerce_value(param_values[name], ptype, name)
                except ValueError as e:
                    errors.append(str(e))
            elif has_default:
                resolved[name] = deepcopy(param['default'])
            elif required:
                errors.append(f'Required parameter "{name}" is missing')
            else:
                resolved[name] = None

        if errors:
            raise TemplateValidationError(errors)

        schema_errors = TemplateService.validate_against_schema(template)
        if schema_errors:
            raise TemplateValidationError(schema_errors)

        qs = TemplateService._expand_date_ranges(template['query_structure'], resolved)
        concrete = TemplateService._walk_and_substitute(qs, resolved, param_defs)

        for cte in concrete.get('ctes', []):
            if 'queryStructure' in cte:
                pass

        return concrete

    @staticmethod
    def build_template(name, query_structure, parameters, description='', version=1):
        param_errors = []
        for param in parameters:
            param_errors.extend(TemplateService.validate_parameter_definition(param))

        names = [p['name'] for p in parameters]
        if len(names) != len(set(names)):
            param_errors.append('Duplicate parameter names are not allowed')

        if param_errors:
            raise TemplateValidationError(param_errors)

        schema_refs = TemplateService.extract_schema_refs(query_structure)

        return {
            'name': name,
            'description': description,
            'version': version,
            'query_structure': deepcopy(query_structure),
            'parameters': deepcopy(parameters),
            'schema_refs': schema_refs,
        }
