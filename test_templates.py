"""
Tests for reusable parameterized query templates.

Covers:
- Parameter type validation and coercion (string, integer, number, boolean, date, lists, date_range)
- Required/default constraints
- Template instantiation only replaces values, not SQL structure
- Self-join, NULL, empty IN, date range, illegal types
- Schema migration errors when fields are deleted
- Version incrementing on update
- Save/share persistence
- API CRUD and instantiation endpoints
"""
import json
import pytest
from sqlalchemy import text
from app.services.template_service import TemplateService, TemplateValidationError
from app.services.sql_generator import SQLGenerator
from app.services.security_service import SecurityService
from app.services.query_executor import QueryExecutor
from app.models import QueryTemplate, db as _db


def _make_simple_template():
    """A simple template with one string parameter for country filter."""
    qs = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't1', 'columnName': 'country'},
        ],
        'where': {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=',
                 'value': {'$param': 'country'}},
            ],
        },
        'having': None,
        'aggregations': [],
        'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': {'$param': 'page_size'},
    }
    params = [
        {'name': 'country', 'type': 'string', 'required': True,
         'description': 'Country code'},
        {'name': 'page_size', 'type': 'integer', 'required': False, 'default': 10},
    ]
    return qs, params


class TestParameterTypeCoercion:
    def test_string_param(self):
        val = TemplateService._coerce_value('US', 'string', 'p')
        assert val == 'US'

    def test_string_rejects_non_string(self):
        with pytest.raises(ValueError, match='expects a string'):
            TemplateService._coerce_value(123, 'string', 'p')

    def test_integer_param_from_int(self):
        assert TemplateService._coerce_value(42, 'integer', 'p') == 42

    def test_integer_param_from_string(self):
        assert TemplateService._coerce_value('42', 'integer', 'p') == 42

    def test_integer_rejects_bool(self):
        with pytest.raises(ValueError, match='expects an integer'):
            TemplateService._coerce_value(True, 'integer', 'p')

    def test_integer_rejects_alpha(self):
        with pytest.raises(ValueError, match='expects an integer'):
            TemplateService._coerce_value('abc', 'integer', 'p')

    def test_number_param(self):
        assert TemplateService._coerce_value(3.14, 'number', 'p') == 3.14
        assert TemplateService._coerce_value('2.5', 'number', 'p') == 2.5

    def test_boolean_param(self):
        assert TemplateService._coerce_value(True, 'boolean', 'p') is True
        assert TemplateService._coerce_value('false', 'boolean', 'p') is False
        assert TemplateService._coerce_value('yes', 'boolean', 'p') is True

    def test_date_param_valid(self):
        assert TemplateService._coerce_value('2025-03-15', 'date', 'p') == '2025-03-15'

    def test_date_param_invalid(self):
        with pytest.raises(ValueError, match='YYYY-MM-DD'):
            TemplateService._coerce_value('15-03-2025', 'date', 'p')

    def test_string_list(self):
        result = TemplateService._coerce_value(['US', 'UK'], 'string_list', 'p')
        assert result == ['US', 'UK']

    def test_string_list_rejects_non_list(self):
        with pytest.raises(ValueError, match='expects a list'):
            TemplateService._coerce_value('US', 'string_list', 'p')

    def test_integer_list(self):
        result = TemplateService._coerce_value(['1', '2', 3], 'integer_list', 'p')
        assert result == [1, 2, 3]

    def test_date_range_valid(self):
        result = TemplateService._coerce_value(
            {'start': '2025-01-01', 'end': '2025-12-31'},
            'date_range', 'p'
        )
        assert result == {'start': '2025-01-01', 'end': '2025-12-31'}

    def test_date_range_start_after_end(self):
        with pytest.raises(ValueError, match='start date must be before'):
            TemplateService._coerce_value(
                {'start': '2025-12-31', 'end': '2025-01-01'},
                'date_range', 'p'
            )

    def test_date_range_missing_end(self):
        with pytest.raises(ValueError, match='requires both start and end'):
            TemplateService._coerce_value({'start': '2025-01-01'}, 'date_range', 'p')

    def test_unknown_type(self):
        with pytest.raises(ValueError, match='Unknown parameter type'):
            TemplateService._coerce_value('x', 'unknown_type', 'p')


class TestTemplateBuild:
    def test_build_extracts_schema_refs(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        ref_keys = {(r['tableId'], r['columnName']) for r in tpl['schema_refs']}
        assert ('t1', 'id') in ref_keys
        assert ('t1', 'first_name') in ref_keys
        assert ('t1', 'country') in ref_keys
        assert tpl['version'] == 1

    def test_build_rejects_duplicate_param_names(self):
        qs, _ = _make_simple_template()
        params = [
            {'name': 'x', 'type': 'string'},
            {'name': 'x', 'type': 'integer'},
        ]
        with pytest.raises(TemplateValidationError, match='Duplicate parameter'):
            TemplateService.build_template('T', qs, params)

    def test_build_rejects_invalid_param_name(self):
        qs, _ = _make_simple_template()
        params = [{'name': '123bad', 'type': 'string'}]
        with pytest.raises(TemplateValidationError, match='alphanumeric'):
            TemplateService.build_template('T', qs, params)

    def test_build_rejects_invalid_type(self):
        qs, _ = _make_simple_template()
        params = [{'name': 'p', 'type': 'json'}]
        with pytest.raises(TemplateValidationError, match='Invalid parameter type'):
            TemplateService.build_template('T', qs, params)

    def test_build_rejects_required_with_default(self):
        qs, _ = _make_simple_template()
        params = [{'name': 'p', 'type': 'string', 'required': True, 'default': 'x'}]
        with pytest.raises(TemplateValidationError, match='both required and have a default'):
            TemplateService.build_template('T', qs, params)


class TestTemplateInstantiation:
    def test_simple_string_param(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        concrete = TemplateService.instantiate(tpl, {'country': 'Germany'})
        where = concrete['where']['children'][0]
        assert where['value'] == 'Germany'
        assert '$param' not in json.dumps(concrete)

    def test_integer_limit_param(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        concrete = TemplateService.instantiate(tpl, {'country': 'US', 'page_size': 25})
        assert concrete['limit'] == 25

    def test_default_value_applied(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        concrete = TemplateService.instantiate(tpl, {'country': 'US'})
        assert concrete['limit'] == 10

    def test_required_param_missing_raises(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        with pytest.raises(TemplateValidationError, match='Required parameter "country"'):
            TemplateService.instantiate(tpl, {})

    def test_wrong_type_raises(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        with pytest.raises(TemplateValidationError, match='expects a string'):
            TemplateService.instantiate(tpl, {'country': 123})

    def test_concrete_produces_valid_sql(self, db_connection):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        concrete = TemplateService.instantiate(tpl, {'country': 'US', 'page_size': 5})
        result = QueryExecutor.generate_sql(concrete)
        SecurityService.validate_readonly_sql(result['sql'])
        rows = db_connection.execute(text(result['sql']), result['params']).fetchall()
        assert len(rows) <= 5
        for row in rows:
            assert row[2] == 'US'

    def test_self_join_template(self, db_connection):
        qs = {
            'tables': [
                {'id': 'e1', 'tableName': 'employee', 'alias': 'e1'},
                {'id': 'e2', 'tableName': 'employee', 'alias': 'e2'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'INNER',
                'leftTableId': 'e1', 'leftColumn': 'department',
                'rightTableId': 'e2', 'rightColumn': 'department',
                'leftTable': 'employee', 'rightTable': 'employee',
            }],
            'selectedFields': [
                {'tableId': 'e1', 'columnName': 'first_name', 'alias': 'name1'},
                {'tableId': 'e2', 'columnName': 'first_name', 'alias': 'name2'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 'e1', 'columnName': 'department', 'cmp': '=',
                     'value': {'$param': 'dept'}},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 100,
        }
        params = [{'name': 'dept', 'type': 'string', 'required': True}]
        tpl = TemplateService.build_template('SelfJoin', qs, params)
        concrete = TemplateService.instantiate(tpl, {'dept': 'Sales'})
        result = QueryExecutor.generate_sql(concrete)
        rows = db_connection.execute(text(result['sql']), result['params']).fetchall()
        for row in rows:
            assert row is not None
        assert '"e1"' in result['sql']
        assert '"e2"' in result['sql']

    def test_null_parameter_handling(self):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'email', 'cmp': 'IS NULL'},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        params = []
        tpl = TemplateService.build_template('NullTest', qs, params)
        concrete = TemplateService.instantiate(tpl, {})
        result = QueryExecutor.generate_sql(concrete)
        assert 'IS NULL' in result['sql']

    def test_empty_in_list_parameter(self, db_connection):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN',
                     'value': {'$param': 'countries'}},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        params = [{'name': 'countries', 'type': 'string_list', 'required': True}]
        tpl = TemplateService.build_template('EmptyIn', qs, params)
        concrete = TemplateService.instantiate(tpl, {'countries': []})
        result = QueryExecutor.generate_sql(concrete)
        rows = db_connection.execute(text(result['sql']), result['params']).fetchall()
        assert len(rows) == 0
        assert '1 = 0' in result['sql']

    def test_in_list_with_values(self, db_connection):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'country'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN',
                     'value': {'$param': 'countries'}},
                ],
            },
            'having': None, 'aggregations': [],
            'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
            'limit': 100,
        }
        params = [{'name': 'countries', 'type': 'string_list', 'required': True}]
        tpl = TemplateService.build_template('InList', qs, params)
        concrete = TemplateService.instantiate(tpl, {'countries': ['US', 'UK']})
        result = QueryExecutor.generate_sql(concrete)
        rows = db_connection.execute(text(result['sql']), result['params']).fetchall()
        for row in rows:
            assert row[1] in ('US', 'UK')

    def test_date_range_time_window(self, db_connection):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'order', 'alias': 'o'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'order_date'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'order_date',
                     'cmp': 'BETWEEN', 'paramRef': 'date_window'},
                ],
            },
            'having': None, 'aggregations': [],
            'orderBy': [{'tableId': 't1', 'columnName': 'order_date', 'direction': 'ASC'}],
            'limit': 100,
        }
        params = [{'name': 'date_window', 'type': 'date_range', 'required': True,
                   'description': 'Order date window'}]
        tpl = TemplateService.build_template('DateRange', qs, params)
        concrete = TemplateService.instantiate(tpl, {
            'date_window': {'start': '2025-03-01', 'end': '2025-03-31'}
        })
        result = QueryExecutor.generate_sql(concrete)
        assert '>=' in result['sql']
        assert '<=' in result['sql']
        rows = db_connection.execute(text(result['sql']), result['params']).fetchall()
        for row in rows:
            d = str(row[1])
            assert '2025-03-01' <= d <= '2025-03-31'

    def test_integer_list_for_in(self, db_connection):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'product', 'alias': 'p'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'name'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'id', 'cmp': 'IN',
                     'value': {'$param': 'ids'}},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        params = [{'name': 'ids', 'type': 'integer_list', 'required': True}]
        tpl = TemplateService.build_template('IntList', qs, params)
        concrete = TemplateService.instantiate(tpl, {'ids': [1, 2, 3]})
        result = QueryExecutor.generate_sql(concrete)
        rows = db_connection.execute(text(result['sql']), result['params']).fetchall()
        assert len(rows) == 3
        ids = {row[0] for row in rows}
        assert ids == {1, 2, 3}

    def test_structure_not_modified_by_instantiation(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        original_where = json.dumps(tpl['query_structure']['where'])
        TemplateService.instantiate(tpl, {'country': 'US'})
        assert json.dumps(tpl['query_structure']['where']) == original_where

    def test_boolean_param(self, db_connection):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'product', 'alias': 'p'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'stock', 'cmp': '>',
                     'value': {'$param': 'min_stock'}},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        params = [{'name': 'min_stock', 'type': 'integer', 'required': True}]
        tpl = TemplateService.build_template('Bool', qs, params)
        with pytest.raises(TemplateValidationError, match='expects an integer, got boolean'):
            TemplateService.instantiate(tpl, {'min_stock': True})

    def test_illegal_string_in_integer_rejected(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Test', qs, params)
        with pytest.raises(TemplateValidationError, match='expects an integer'):
            TemplateService.instantiate(tpl, {'country': 'US', 'page_size': 'abc'})


class TestSchemaMigration:
    def test_missing_column_gives_located_error(self, app):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'nonexistent_col'}],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [], 'limit': 10,
        }
        params = []
        tpl = TemplateService.build_template('Bad', qs, params)
        tpl['schema_refs'].append({
            'tableId': 't1', 'tableName': 'customer',
            'columnName': 'nonexistent_col', 'location': 'selectedFields',
        })
        errors = TemplateService.validate_against_schema(tpl)
        assert len(errors) >= 1
        assert any('nonexistent_col' in e and 't1' in e for e in errors)
        assert any('Migration error' in e for e in errors)

    def test_missing_table_gives_located_error(self, app):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'ghost_table', 'alias': 'g'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [], 'limit': 10,
        }
        tpl = TemplateService.build_template('Bad', qs, [])
        errors = TemplateService.validate_against_schema(tpl)
        assert any('ghost_table' in e and 't1' in e for e in errors)

    def test_instantiation_blocks_on_broken_schema(self, app):
        qs = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [], 'limit': 10,
        }
        tpl = TemplateService.build_template('OK', qs, [])
        tpl['schema_refs'].append({
            'tableId': 't1', 'tableName': 'customer',
            'columnName': 'deleted_column', 'location': 'where',
        })
        with pytest.raises(TemplateValidationError, match='Migration error'):
            TemplateService.instantiate(tpl, {})

    def test_valid_schema_passes(self, app):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('OK', qs, params)
        errors = TemplateService.validate_against_schema(tpl)
        assert errors == []


class TestTemplatePersistence:
    def test_save_and_retrieve_template(self, app, client):
        qs, params = _make_simple_template()
        built = TemplateService.build_template('My Template', qs, params,
                                               description='A test template')
        with app.app_context():
            tpl = QueryTemplate(
                name=built['name'], description=built['description'],
                version=built['version'], query_structure=built['query_structure'],
                parameters=built['parameters'], schema_refs=built['schema_refs'],
            )
            _db.session.add(tpl)
            _db.session.commit()
            tpl_id = tpl.id

        resp = client.get(f'/api/templates/{tpl_id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'My Template'
        assert data['version'] == 1
        assert len(data['parameters']) == 2

    def test_version_increments_on_update(self, app, client):
        qs, params = _make_simple_template()
        with app.app_context():
            built = TemplateService.build_template('V1', qs, params)
            tpl = QueryTemplate(**{k: built[k] for k in
                ('name', 'description', 'version', 'query_structure',
                 'parameters', 'schema_refs')})
            _db.session.add(tpl)
            _db.session.commit()
            tpl_id = tpl.id

        new_qs = json.loads(json.dumps(qs))
        new_qs['limit'] = 50
        resp = client.put(f'/api/templates/{tpl_id}',
                          json={'query_structure': new_qs, 'parameters': params})
        assert resp.status_code == 200
        assert resp.get_json()['version'] == 2

    def test_share_token_roundtrip(self, app, client):
        qs, params = _make_simple_template()
        with app.app_context():
            built = TemplateService.build_template('Shareable', qs, params)
            tpl = QueryTemplate(**{k: built[k] for k in
                ('name', 'description', 'version', 'query_structure',
                 'parameters', 'schema_refs')})
            _db.session.add(tpl)
            _db.session.commit()
            tpl_id = tpl.id

        resp = client.post(f'/api/templates/{tpl_id}/share', json={'expires_in_hours': 24})
        assert resp.status_code == 200
        token = resp.get_json()['token']

        shared = client.get(f'/api/share/template/{token}')
        assert shared.status_code == 200
        assert shared.get_json()['template']['name'] == 'Shareable'


class TestTemplateApi:
    def _create_template_via_api(self, client, name='API Template'):
        qs, params = _make_simple_template()
        resp = client.post('/api/templates', json={
            'name': name,
            'description': 'created via API',
            'query_structure': qs,
            'parameters': params,
        })
        assert resp.status_code == 201
        return resp.get_json()

    def test_create_template(self, client):
        data = self._create_template_via_api(client)
        assert data['id'] > 0
        assert data['version'] == 1
        assert len(data['schema_refs']) >= 3

    def test_list_templates(self, client):
        self._create_template_via_api(client, 'T1')
        self._create_template_via_api(client, 'T2')
        resp = client.get('/api/templates')
        assert resp.status_code == 200
        names = [t['name'] for t in resp.get_json()]
        assert 'T1' in names
        assert 'T2' in names

    def test_delete_template(self, client):
        tpl = self._create_template_via_api(client)
        resp = client.delete(f"/api/templates/{tpl['id']}")
        assert resp.status_code == 204
        resp2 = client.get(f"/api/templates/{tpl['id']}")
        assert resp2.status_code == 404

    def test_instantiate_via_api(self, client, db_connection):
        tpl = self._create_template_via_api(client)
        resp = client.post(f"/api/templates/{tpl['id']}/instantiate",
                           json={'parameters': {'country': 'US', 'page_size': 3}})
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'sql' in data
        assert 'params' in data
        assert data['templateVersion'] == 1
        rows = db_connection.execute(text(data['sql']), data['params']).fetchall()
        assert len(rows) <= 3
        for row in rows:
            assert row[2] == 'US'

    def test_execute_via_api(self, client):
        tpl = self._create_template_via_api(client)
        resp = client.post(f"/api/templates/{tpl['id']}/execute",
                           json={'parameters': {'country': 'UK'}})
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'rows' in data
        assert 'columns' in data
        assert data['rowCount'] >= 0
        for row in data['rows']:
            assert row[2] == 'UK'

    def test_instantiate_missing_required_returns_400(self, client):
        tpl = self._create_template_via_api(client)
        resp = client.post(f"/api/templates/{tpl['id']}/instantiate",
                           json={'parameters': {}})
        assert resp.status_code == 400
        assert 'Required parameter' in resp.get_json()['error']

    def test_instantiate_wrong_type_returns_400(self, client):
        tpl = self._create_template_via_api(client)
        resp = client.post(f"/api/templates/{tpl['id']}/instantiate",
                           json={'parameters': {'country': 999}})
        assert resp.status_code == 400
        assert 'expects a string' in resp.get_json()['error']

    def test_validate_endpoint(self, client):
        tpl = self._create_template_via_api(client)
        resp = client.post(f"/api/templates/{tpl['id']}/validate")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['valid'] is True
        assert data['errors'] == []

    def test_create_rejects_invalid_param_type(self, client):
        qs, _ = _make_simple_template()
        resp = client.post('/api/templates', json={
            'name': 'Bad',
            'query_structure': qs,
            'parameters': [{'name': 'x', 'type': 'invalid_type'}],
        })
        assert resp.status_code == 400

    def test_explain_and_execute_share_ast(self, client):
        tpl = self._create_template_via_api(client)
        inst = client.post(f"/api/templates/{tpl['id']}/instantiate",
                           json={'parameters': {'country': 'Germany'}}).get_json()
        exec_resp = client.post(f"/api/templates/{tpl['id']}/execute",
                                json={'parameters': {'country': 'Germany'}})
        exec_data = exec_resp.get_json()
        assert inst['sql'] == exec_data.get('sql', '')


class TestTemplateAstRoundTrip:
    def test_json_serialization_roundtrip(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('RoundTrip', qs, params)
        serialized = json.dumps(tpl)
        restored = json.loads(serialized)

        c1 = TemplateService.instantiate(tpl, {'country': 'US'})
        c2 = TemplateService.instantiate(restored, {'country': 'US'})
        assert json.dumps(c1, sort_keys=True) == json.dumps(c2, sort_keys=True)

    def test_table_instance_ids_stable_across_instantiation(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('Stable', qs, params)
        c1 = TemplateService.instantiate(tpl, {'country': 'US'})
        c2 = TemplateService.instantiate(tpl, {'country': 'UK'})
        assert c1['tables'][0]['id'] == c2['tables'][0]['id'] == 't1'
        assert c1['tables'][0]['alias'] == c2['tables'][0]['alias'] == 'c'

    def test_params_only_appear_in_values(self):
        qs, params = _make_simple_template()
        tpl = TemplateService.build_template('NoInjection', qs, params)
        concrete = TemplateService.instantiate(tpl, {'country': 'US'})
        sql_result = QueryExecutor.generate_sql(concrete)
        assert '$param' not in sql_result['sql']
        assert 'paramRef' not in sql_result['sql']
        SecurityService.validate_readonly_sql(sql_result['sql'])
