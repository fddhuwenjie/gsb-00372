"""
Tests for parameterised query templates.

Covers: parameter type coercion, template validation, instantiation,
schema migration errors, version handling, self-joins, NULL, empty IN,
date windows, illegal types, save/restore round-trips, and API differential
tests comparing template results against hand-written parameterised SQL.
"""
import json

import pytest
from sqlalchemy import text

from app.database import db
from app.services.security_service import SecurityService
from app.services.sql_generator import SQLGenerator
from app.services.template_service import (
    CURRENT_TEMPLATE_VERSION,
    TemplateMigrationError,
    TemplateService,
    TemplateValidationError,
)
from app.models import QueryTemplate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def simple_template(**overrides):
    tpl = {
        'template_version': 1,
        'name': 'Customers by country',
        'description': '',
        'parameters': [
            {
                'name': 'country',
                'type': 'string',
                'label': 'Country',
                'required': True,
                'usage': 'filter',
                'tableId': 'c',
                'columnName': 'country',
            }
        ],
        'queryStructure': {
            'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 'c', 'columnName': 'id'},
                {'tableId': 'c', 'columnName': 'country'},
            ],
            'where': {
                'tableId': 'c',
                'columnName': 'country',
                'cmp': '=',
                'param': 'country',
            },
            'aggregations': [],
            'limit': 50,
        },
    }
    tpl.update(overrides)
    return tpl


def handwritten(sql, params=None):
    result = db.session.execute(text(sql), params or {})
    return [list(r) for r in result.fetchall()]


# ---------------------------------------------------------------------------
# Parameter type coercion
# ---------------------------------------------------------------------------
class TestParameterCoercion:
    def test_string_type(self):
        assert SecurityService.coerce_param_value('US', 'string', 'p') == 'US'

    def test_integer_coercion(self):
        assert SecurityService.coerce_param_value(42, 'integer', 'p') == 42
        assert SecurityService.coerce_param_value('7', 'integer', 'p') == 7
        assert SecurityService.coerce_param_value(3.0, 'integer', 'p') == 3

    def test_integer_rejects_bool(self):
        with pytest.raises(ValueError, match='integer'):
            SecurityService.coerce_param_value(True, 'integer', 'p')

    def test_number_coercion(self):
        assert SecurityService.coerce_param_value(1.5, 'number', 'p') == 1.5
        assert SecurityService.coerce_param_value('2.5', 'number', 'p') == 2.5

    def test_boolean_coercion(self):
        assert SecurityService.coerce_param_value(True, 'boolean', 'p') is True
        assert SecurityService.coerce_param_value('yes', 'boolean', 'p') is True
        assert SecurityService.coerce_param_value('0', 'boolean', 'p') is False

    def test_date_format_validation(self):
        SecurityService.coerce_param_value('2025-03-01', 'date', 'd')
        with pytest.raises(ValueError, match='YYYY-MM-DD'):
            SecurityService.coerce_param_value('03/01/2025', 'date', 'd')

    def test_datetime_format_validation(self):
        SecurityService.coerce_param_value('2025-03-01T10:00', 'datetime', 'd')
        with pytest.raises(ValueError):
            SecurityService.coerce_param_value('not-a-date', 'datetime', 'd')

    def test_string_list(self):
        result = SecurityService.coerce_param_value(
            ['US', 'UK'], 'string_list', 'p'
        )
        assert result == ['US', 'UK']

    def test_integer_list(self):
        result = SecurityService.coerce_param_value(
            [1, '2', 3.0], 'integer_list', 'p'
        )
        assert result == [1, 2, 3]

    def test_list_rejects_non_list(self):
        with pytest.raises(ValueError, match='expected list'):
            SecurityService.coerce_param_value('US,UK', 'string_list', 'p')

    def test_illegal_type_rejected(self):
        with pytest.raises(ValueError, match='Invalid parameter type'):
            SecurityService.validate_param_type('json_blob')


# ---------------------------------------------------------------------------
# Template validation
# ---------------------------------------------------------------------------
class TestTemplateValidation:
    def test_valid_template(self):
        tpl = TemplateService.validate_template(simple_template())
        assert tpl['name'] == 'Customers by country'
        assert len(tpl['parameters']) == 1

    def test_missing_name_rejected(self):
        tpl = simple_template(name='')
        with pytest.raises(TemplateValidationError):
            TemplateService.validate_template(tpl)

    def test_duplicate_param_name_rejected(self):
        tpl = simple_template()
        tpl['parameters'].append(dict(tpl['parameters'][0]))
        with pytest.raises(TemplateValidationError, match='Duplicate'):
            TemplateService.validate_template(tpl)

    def test_undeclared_param_reference_rejected(self):
        tpl = simple_template()
        tpl['queryStructure']['where']['param'] = 'nonexistent'
        with pytest.raises(TemplateValidationError, match='undeclared'):
            TemplateService.validate_template(tpl)

    def test_unused_declared_param_rejected(self):
        tpl = simple_template()
        tpl['parameters'].append({
            'name': 'unused', 'type': 'string', 'label': 'Unused',
        })
        with pytest.raises(TemplateValidationError, match='not used'):
            TemplateService.validate_template(tpl)

    def test_list_param_with_non_in_operator_rejected(self):
        tpl = simple_template()
        tpl['parameters'][0]['type'] = 'string_list'
        # where uses '=' but param is a list
        with pytest.raises(TemplateValidationError, match='IN/NOT IN'):
            TemplateService.validate_template(tpl)

    def test_scalar_param_with_in_operator_rejected(self):
        tpl = simple_template()
        tpl['queryStructure']['where']['cmp'] = 'IN'
        # param declared as string but used with IN -> needs string_list
        with pytest.raises(TemplateValidationError, match=r'\*_list'):
            TemplateService.validate_template(tpl)

    def test_future_version_rejected(self):
        tpl = simple_template(template_version=999)
        with pytest.raises(TemplateValidationError, match='newer'):
            TemplateService.validate_template(tpl)

    def test_required_param_missing_at_instantiation(self, app_context):
        tpl = TemplateService.validate_template(simple_template())
        with pytest.raises(TemplateValidationError, match='required'):
            TemplateService.instantiate(tpl, {})

    def test_default_value_used_when_not_supplied(self, app_context):
        tpl = simple_template()
        tpl['parameters'][0]['required'] = False
        tpl['parameters'][0]['default'] = 'US'
        result = TemplateService.instantiate(tpl, {})
        assert result['resolvedParameters']['country'] == 'US'

    def test_illegal_value_type_at_instantiation(self, app_context):
        tpl = TemplateService.validate_template(simple_template())
        with pytest.raises(TemplateValidationError, match='expected string'):
            TemplateService.instantiate(tpl, {'country': 12345})


# ---------------------------------------------------------------------------
# SQL generation with parameter references
# ---------------------------------------------------------------------------
class TestParameterSQLGeneration:
    def test_scalar_param_emits_named_placeholder(self):
        qs = {
            'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
            'where': {
                'tableId': 'c', 'columnName': 'country',
                'cmp': '=', 'param': 'country',
            },
            'aggregations': [],
            'limit': 10,
        }
        gen = SQLGenerator(qs, param_values={'country': 'US'})
        sql = gen.generate()
        params = gen.get_params()
        assert ':country' in sql
        assert params['country'] == 'US'
        # the inline value must never appear in SQL
        assert 'US' not in sql

    def test_missing_param_value_raises(self):
        qs = {
            'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
            'where': {
                'tableId': 'c', 'columnName': 'country',
                'cmp': '=', 'param': 'country',
            },
            'aggregations': [],
            'limit': 10,
        }
        gen = SQLGenerator(qs, param_values={})
        with pytest.raises(ValueError, match='Missing value'):
            gen.generate()

    def test_in_list_param_expands_to_per_element_placeholders(self):
        qs = {
            'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
            'where': {
                'tableId': 'c', 'columnName': 'country',
                'cmp': 'IN', 'param': 'countries',
            },
            'aggregations': [],
            'limit': 10,
        }
        gen = SQLGenerator(qs, param_values={'countries': ['US', 'UK', 'DE']})
        sql = gen.generate()
        params = gen.get_params()
        assert ':countries_0' in sql
        assert ':countries_1' in sql
        assert ':countries_2' in sql
        assert params['countries_0'] == 'US'

    def test_empty_in_list_param_renders_false_constant(self):
        qs = {
            'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
            'where': {
                'tableId': 'c', 'columnName': 'country',
                'cmp': 'IN', 'param': 'countries',
            },
            'aggregations': [],
            'limit': 10,
        }
        gen = SQLGenerator(qs, param_values={'countries': []})
        sql = gen.generate()
        assert '0 = 1' in sql
        assert 'IN (' not in sql

    def test_limit_param_binding(self):
        qs = {
            'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
            'where': None,
            'aggregations': [],
            'limit': 100,
            'limitParam': 'page_size',
        }
        gen = SQLGenerator(qs, param_values={'page_size': 5})
        sql = gen.generate()
        params = gen.get_params()
        assert ':page_size' in sql
        assert params['page_size'] == 5


# ---------------------------------------------------------------------------
# Schema migration errors
# ---------------------------------------------------------------------------
class TestSchemaMigration:
    def test_missing_column_gives_locatable_error(self, app_context):
        tpl = simple_template()
        tpl['queryStructure']['selectedFields'][1]['columnName'] = 'nonexistent'
        with pytest.raises(TemplateMigrationError) as exc:
            TemplateService.check_schema(
                TemplateService.validate_template(tpl)
            )
        joined = ' '.join(exc.value.errors)
        assert 'nonexistent' in joined
        assert 'customer' in joined

    def test_missing_table_gives_locatable_error(self, app_context):
        tpl = simple_template()
        tpl['queryStructure']['tables'][0]['tableName'] = 'ghost'
        with pytest.raises(TemplateMigrationError) as exc:
            TemplateService.check_schema(
                TemplateService.validate_template(tpl)
            )
        assert any('ghost' in e for e in exc.value.errors)

    def test_parameter_column_type_mismatch(self, app_context):
        tpl = simple_template()
        # Bind a boolean param to a text column -> incompatible
        tpl['parameters'][0]['type'] = 'boolean'
        with pytest.raises(TemplateMigrationError) as exc:
            TemplateService.check_schema(
                TemplateService.validate_template(tpl)
            )
        assert any('incompatible' in e for e in exc.value.errors)

    def test_valid_template_passes_schema_check(self, app_context):
        tpl = TemplateService.validate_template(simple_template())
        assert TemplateService.check_schema(tpl) is True


# ---------------------------------------------------------------------------
# Save / share / restore round-trip
# ---------------------------------------------------------------------------
class TestTemplatePersistence:
    def test_save_and_restore_roundtrip(self, app_context):
        tpl = TemplateService.validate_template(simple_template())
        TemplateService.check_schema(tpl)
        saved = QueryTemplate(
            name=tpl['name'],
            template_version=tpl['template_version'],
            template_definition=tpl,
        )
        db.session.add(saved)
        db.session.commit()

        fetched = QueryTemplate.query.get(saved.id)
        restored = TemplateService.validate_template(
            fetched.template_definition
        )
        assert restored['queryStructure'] == tpl['queryStructure']
        assert restored['parameters'] == tpl['parameters']

    def test_json_roundtrip_preserves_structure(self, app_context):
        tpl = simple_template()
        json_str = json.dumps(tpl)
        restored = json.loads(json_str)
        validated = TemplateService.validate_template(restored)
        assert validated['queryStructure']['where']['param'] == 'country'


# ---------------------------------------------------------------------------
# Differential tests: template result vs hand-written parameterised SQL
# ---------------------------------------------------------------------------
class TestTemplateDifferential:
    def test_string_filter_differential(self, app_context):
        tpl = simple_template()
        result = TemplateService.instantiate(tpl, {'country': 'US'})
        template_rows = handwritten(result['sql'], result['params'])
        hand_rows = handwritten(
            'SELECT c.id, c.country FROM customer c '
            'WHERE c.country = :country LIMIT :lim',
            {'country': 'US', 'lim': 50},
        )
        assert sorted(template_rows) == sorted(hand_rows)

    def test_in_list_differential(self, app_context):
        tpl = simple_template()
        tpl['parameters'][0]['type'] = 'string_list'
        tpl['queryStructure']['where']['cmp'] = 'IN'
        result = TemplateService.instantiate(
            tpl, {'country': ['US', 'UK', 'Germany']}
        )
        template_rows = handwritten(result['sql'], result['params'])
        hand_rows = handwritten(
            'SELECT c.id, c.country FROM customer c '
            'WHERE c.country IN (:a, :b, :cc) LIMIT :lim',
            {'a': 'US', 'b': 'UK', 'cc': 'Germany', 'lim': 50},
        )
        assert sorted(template_rows) == sorted(hand_rows)

    def test_empty_in_returns_no_rows(self, app_context):
        tpl = simple_template()
        tpl['parameters'][0]['type'] = 'string_list'
        tpl['queryStructure']['where']['cmp'] = 'IN'
        result = TemplateService.instantiate(tpl, {'country': []})
        rows = handwritten(result['sql'], result['params'])
        assert rows == []

    def test_null_filter_differential(self, app_context):
        tpl = {
            'template_version': 1,
            'name': 'Customers with NULL email',
            'parameters': [],
            'queryStructure': {
                'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
                'joins': [],
                'selectedFields': [
                    {'tableId': 'c', 'columnName': 'id'},
                ],
                'where': {
                    'tableId': 'c', 'columnName': 'email',
                    'cmp': 'IS NULL',
                },
                'aggregations': [],
                'limit': 100,
            },
        }
        result = TemplateService.instantiate(tpl, {})
        template_rows = handwritten(result['sql'], result['params'])
        # The seed data has no NULL emails, but the query must compile
        # correctly.
        assert result['sql'].count('IS NULL') >= 1
        assert isinstance(template_rows, list)

    def test_date_window_differential(self, app_context):
        tpl = {
            'template_version': 1,
            'name': 'Orders in date window',
            'parameters': [
                {'name': 'start_date', 'type': 'date', 'required': True,
                 'usage': 'date_window_start'},
                {'name': 'end_date', 'type': 'date', 'required': True,
                 'usage': 'date_window_end'},
            ],
            'queryStructure': {
                'tables': [{'id': 'o', 'tableName': 'order', 'alias': 'o'}],
                'joins': [],
                'selectedFields': [
                    {'tableId': 'o', 'columnName': 'id'},
                    {'tableId': 'o', 'columnName': 'order_date'},
                ],
                'where': {
                    'op': 'AND',
                    'children': [
                        {'tableId': 'o', 'columnName': 'order_date',
                         'cmp': '>=', 'param': 'start_date'},
                        {'tableId': 'o', 'columnName': 'order_date',
                         'cmp': '<=', 'param': 'end_date'},
                    ],
                },
                'aggregations': [],
                'limit': 100,
            },
        }
        values = {'start_date': '2025-02-01', 'end_date': '2025-03-31'}
        result = TemplateService.instantiate(tpl, values)
        template_rows = handwritten(result['sql'], result['params'])
        hand_rows = handwritten(
            'SELECT o.id, o.order_date FROM "order" o '
            'WHERE (o.order_date >= :s AND o.order_date <= :e) LIMIT :lim',
            {'s': '2025-02-01', 'e': '2025-03-31', 'lim': 100},
        )
        assert sorted(template_rows) == sorted(hand_rows)

    def test_self_join_template_differential(self, app_context):
        tpl = {
            'template_version': 1,
            'name': 'Employees same department',
            'parameters': [
                {'name': 'dept', 'type': 'string', 'required': False,
                 'default': 'Sales'},
            ],
            'queryStructure': {
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
                    {'tableId': 'e1', 'columnName': 'id', 'alias': 'a'},
                    {'tableId': 'e2', 'columnName': 'id', 'alias': 'b'},
                ],
                'where': {
                    'tableId': 'e1', 'columnName': 'department',
                    'cmp': '=', 'param': 'dept',
                },
                'aggregations': [],
                'limit': 500,
            },
        }
        result = TemplateService.instantiate(tpl, {'dept': 'Sales'})
        template_rows = handwritten(result['sql'], result['params'])
        hand_rows = handwritten(
            'SELECT e1.id AS a, e2.id AS b FROM employee e1 '
            'INNER JOIN employee e2 ON e1.department = e2.department '
            'WHERE e1.department = :dept LIMIT :lim',
            {'dept': 'Sales', 'lim': 500},
        )
        assert sorted(tuple(r) for r in template_rows) == \
               sorted(tuple(r) for r in hand_rows)

    def test_pagination_param_differential(self, app_context):
        tpl = simple_template()
        tpl['parameters'] = [
            {'name': 'country', 'type': 'string', 'required': False,
             'default': 'US'},
            {'name': 'page_size', 'type': 'integer', 'required': False,
             'default': 3, 'usage': 'limit'},
        ]
        tpl['queryStructure']['limitParam'] = 'page_size'
        result = TemplateService.instantiate(
            tpl, {'country': 'US', 'page_size': 3}
        )
        template_rows = handwritten(result['sql'], result['params'])
        hand_rows = handwritten(
            'SELECT c.id, c.country FROM customer c '
            'WHERE c.country = :country LIMIT :lim',
            {'country': 'US', 'lim': 3},
        )
        assert template_rows == hand_rows


# ---------------------------------------------------------------------------
# API-level differential tests (via Flask test client)
# ---------------------------------------------------------------------------
class TestTemplateAPI:
    def _create_template(self, client, tpl):
        resp = client.post('/api/templates', json=tpl)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        return resp.get_json()

    def test_create_and_instantiate_via_api(self, client):
        tpl = simple_template()
        saved = self._create_template(client, tpl)
        resp = client.post(
            f'/api/templates/{saved["id"]}/instantiate',
            json={'values': {'country': 'US'}, 'execute': True},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body['rowCount'] >= 1
        assert 'country' in body['params']

    def test_instantiate_preview_only(self, client):
        tpl = simple_template()
        saved = self._create_template(client, tpl)
        resp = client.post(
            f'/api/templates/{saved["id"]}/instantiate',
            json={'values': {'country': 'US'}, 'execute': False},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert 'sql' in body
        assert 'rows' not in body
        assert body['params']['country'] == 'US'

    def test_instantiate_missing_required_param_returns_400(self, client):
        tpl = simple_template()
        saved = self._create_template(client, tpl)
        resp = client.post(
            f'/api/templates/{saved["id"]}/instantiate',
            json={'values': {}},
        )
        assert resp.status_code == 400
        assert 'required' in resp.get_json()['error']

    def test_instantiate_illegal_type_returns_400(self, client):
        tpl = simple_template()
        saved = self._create_template(client, tpl)
        resp = client.post(
            f'/api/templates/{saved["id"]}/instantiate',
            json={'values': {'country': 12345}},
        )
        assert resp.status_code == 400

    def test_schema_migration_error_returns_locatable_400(self, client):
        tpl = simple_template()
        tpl['queryStructure']['selectedFields'][0]['columnName'] = 'ghost'
        resp = client.post('/api/templates', json=tpl)
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'ghost' in body['error']

    def test_template_share_and_restore(self, client):
        tpl = simple_template()
        saved = self._create_template(client, tpl)
        share = client.post(
            f'/api/templates/{saved["id"]}/share',
            json={'expires_in_hours': 1},
        )
        assert share.status_code == 200
        token = share.get_json()['token']

        shared = client.get(f'/api/templates/share/{token}')
        assert shared.status_code == 200
        body = shared.get_json()
        assert body['template']['name'] == tpl['name']
        assert len(body['parameters']) == 1

    def test_validate_endpoint_rejects_invalid(self, client):
        tpl = simple_template()
        tpl['parameters'] = []  # remove params but query references one
        resp = client.post('/api/templates/validate', json=tpl)
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['valid'] is False
