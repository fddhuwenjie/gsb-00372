"""Parameterized query template tests.

Covers typed parameters (defaults / required / illegal types), filters,
pagination and time windows, instantiation-is-values-only (no SQL splicing),
self-joins, NULL, empty IN, dates, template versioning, save/share/schema
refresh reference stability, and locatable migration errors.
"""
import pytest
from sqlalchemy import text

from app.database import db
from app.services.template_service import TemplateService, TemplateError
from tests.helpers import run_reference


# ----------------------------------------------------------------------
# Template fixtures
# ----------------------------------------------------------------------

def self_join_structure():
    return {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'customer', 'alias': 'c2'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'country',
             'rightTableId': 't2', 'rightColumn': 'country',
             'leftTable': 'customer', 'rightTable': 'customer'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't2', 'columnName': 'city'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
            {'id': 'c2', 'tableId': 't2', 'columnName': 'country', 'cmp': '!=', 'value': 'US'},
        ]},
        'aggregations': [],
        'limit': 100,
        'offset': 0,
    }


def time_window_structure():
    return {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'LEFT', 'leftTableId': 't1', 'leftColumn': 'id',
             'rightTableId': 't2', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't2', 'columnName': 'total_amount'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN', 'value': ['US']},
            {'id': 'c2', 'tableId': 't2', 'columnName': 'order_date', 'cmp': '>=', 'value': '2025-01-01'},
            {'id': 'c3', 'tableId': 't2', 'columnName': 'order_date', 'cmp': '<', 'value': '2025-06-01'},
            {'id': 'c4', 'tableId': 't2', 'columnName': 'employee_id', 'cmp': '=', 'value': 1},
        ]},
        'aggregations': [],
        'limit': 100,
        'offset': 0,
    }


def time_window_parameters():
    return [
        {'id': 'p-countries', 'name': 'countries', 'type': 'string[]', 'required': True,
         'target': {'kind': 'where', 'nodeId': 'c1'}},
        {'id': 'p-from', 'name': 'from_date', 'type': 'date', 'required': False,
         'default': '2025-01-01', 'target': {'kind': 'where', 'nodeId': 'c2'}},
        {'id': 'p-to', 'name': 'to_date', 'type': 'date', 'required': False,
         'default': '2025-06-01', 'target': {'kind': 'where', 'nodeId': 'c3'}},
        {'id': 'p-emp', 'name': 'employee_id', 'type': 'integer', 'required': False,
         'default': 1, 'target': {'kind': 'where', 'nodeId': 'c4'}},
        {'id': 'p-limit', 'name': 'page_size', 'type': 'integer', 'required': False,
         'default': 50, 'target': {'kind': 'limit'}},
        {'id': 'p-offset', 'name': 'page_offset', 'type': 'integer', 'required': False,
         'default': 0, 'target': {'kind': 'offset'}},
    ]


def create_template(client, name='tpl', structure=None, parameters=None):
    response = client.post('/api/templates', json={
        'name': name,
        'parameters': parameters if parameters is not None else time_window_parameters(),
        'query_structure': structure or time_window_structure(),
    })
    assert response.status_code == 201, response.get_json()
    return response.get_json()


# ----------------------------------------------------------------------
# Definition validation
# ----------------------------------------------------------------------

class TestDefinitionValidation:
    def _create(self, client, parameters):
        return client.post('/api/templates', json={
            'name': 'bad',
            'parameters': parameters,
            'query_structure': time_window_structure(),
        })

    def test_duplicate_parameter_name_rejected(self, client):
        params = time_window_parameters()
        params[1] = dict(params[1], name='countries')
        response = self._create(client, params)
        assert response.status_code == 400
        assert any(i['code'] == 'PARAM_NAME_DUPLICATE' for i in response.get_json()['issues'])

    def test_unknown_type_rejected(self, client):
        params = [dict(time_window_parameters()[0], type='json')]
        response = self._create(client, params)
        assert response.status_code == 400
        assert any(i['code'] == 'PARAM_TYPE_INVALID' for i in response.get_json()['issues'])

    def test_optional_parameter_requires_default(self, client):
        params = [dict(time_window_parameters()[4], required=False)]
        del params[0]['default']
        response = self._create(client, params)
        assert response.status_code == 400
        assert any(i['code'] == 'PARAM_DEFAULT_MISSING' for i in response.get_json()['issues'])

    def test_limit_parameter_must_be_integer(self, client):
        params = [dict(time_window_parameters()[4], type='string', default='x')]
        response = self._create(client, params)
        assert response.status_code == 400
        assert any(i['code'] == 'PARAM_TYPE_MISMATCH' for i in response.get_json()['issues'])

    def test_in_clause_requires_list_parameter(self, client):
        params = [dict(time_window_parameters()[0], type='string')]
        response = self._create(client, params)
        assert response.status_code == 400
        assert any(i['code'] == 'PARAM_TYPE_MISMATCH' for i in response.get_json()['issues'])

    def test_missing_target_clause_rejected(self, client):
        params = [dict(time_window_parameters()[0],
                       target={'kind': 'where', 'nodeId': 'no-such-clause'})]
        response = self._create(client, params)
        assert response.status_code == 400
        issues = response.get_json()['issues']
        assert any(i['code'] == 'PARAM_TARGET_MISSING' and 'no-such-clause' in i['message']
                   for i in issues)

    def test_invalid_default_rejected(self, client):
        params = [dict(time_window_parameters()[1], default='not-a-date')]
        response = self._create(client, params)
        assert response.status_code == 400
        assert any(i['code'] == 'PARAM_DEFAULT_INVALID' for i in response.get_json()['issues'])


# ----------------------------------------------------------------------
# Instantiation semantics
# ----------------------------------------------------------------------

class TestInstantiation:
    def test_defaults_and_required(self, client):
        tpl = create_template(client)
        # missing required 'countries'
        response = client.post(f"/api/templates/{tpl['id']}/instantiate", json={'values': {}})
        assert response.status_code == 400
        issue = response.get_json()['issues'][0]
        assert issue['code'] == 'PARAM_VALUE_MISSING'
        assert issue['parameter'] == 'countries'
        assert "parameters[0]" in issue['path']

    def test_unknown_parameter_rejected(self, client):
        tpl = create_template(client)
        response = client.post(f"/api/templates/{tpl['id']}/instantiate",
                               json={'values': {'countries': ['US'], 'hack': 'x'}})
        assert response.status_code == 400
        assert 'hack' in response.get_json()['error']

    @pytest.mark.parametrize('param_name,value,fragment', [
        ('page_size', 'abc', 'page_size'),
        ('page_size', 1.5, 'page_size'),
        ('page_size', True, 'page_size'),
        ('from_date', 'not-a-date', 'from_date'),
        ('from_date', '2025-13-40', 'from_date'),
        ('countries', 'US', 'countries'),          # scalar for list type
        ('countries', [1, 2], 'countries'),        # wrong item type
        ('employee_id', {'x': 1}, 'employee_id'),
    ])
    def test_illegal_value_types_rejected(self, client, param_name, value, fragment):
        tpl = create_template(client)
        values = {'countries': ['US'], param_name: value}
        response = client.post(f"/api/templates/{tpl['id']}/instantiate",
                               json={'values': values})
        assert response.status_code == 400
        assert fragment in response.get_json()['error']

    def test_structure_never_spliced(self, client):
        tpl = create_template(client)
        malicious = "US') OR '1'='1' --"
        first = client.post(f"/api/templates/{tpl['id']}/instantiate",
                            json={'values': {'countries': ['US']}}).get_json()
        second = client.post(f"/api/templates/{tpl['id']}/instantiate",
                             json={'values': {'countries': [malicious]},
                                   # attempt to smuggle structure along with the request
                                   'query_structure': {'tables': []},
                                   'sql': 'DROP TABLE customer'}).get_json()
        assert first['sql'] == second['sql']  # identical structure, only params differ
        assert second['params']['p1'] == malicious
        assert "'1'='1'" not in second['sql']
        assert 'query_structure' in second and second['query_structure']['tables']

    def test_empty_in_parameter(self, client, connection):
        tpl = create_template(client)
        response = client.post(
            f"/api/templates/{tpl['id']}/instantiate",
            json={'values': {'countries': []}, 'execute': True})
        assert response.status_code == 200
        data = response.get_json()
        assert '(1 = 0)' in data['sql']
        _, ref_rows = run_reference(connection, 'SELECT 1 WHERE (1 = 0)')
        assert data['result']['rowCount'] == len(ref_rows) == 0

    def test_null_parameter_value_maps_to_is_null(self, client, connection):
        tpl = create_template(client)
        response = client.post(
            f"/api/templates/{tpl['id']}/instantiate",
            json={'values': {'countries': ['US', 'UK', 'Germany', 'France', 'Spain'],
                             'employee_id': None,
                             'from_date': '2025-01-01',
                             'to_date': '2025-12-31'},
                  'execute': True})
        assert response.status_code == 200
        data = response.get_json()
        assert '"o"."employee_id" IS NULL' in data['sql']
        ref_columns, ref_rows = run_reference(
            connection,
            'SELECT c.first_name, o.total_amount FROM customer c '
            'LEFT JOIN "order" o ON c.id = o.customer_id '
            'WHERE c.country IN (:v1, :v2, :v3, :v4, :v5) '
            'AND o.order_date >= :d1 AND o.order_date < :d2 '
            'AND o.employee_id IS NULL LIMIT :lim',
            {'v1': 'US', 'v2': 'UK', 'v3': 'Germany', 'v4': 'France', 'v5': 'Spain',
             'd1': '2025-01-01', 'd2': '2025-12-31', 'lim': 50})
        assert [tuple(r) for r in data['result']['rows']] == [tuple(r) for r in ref_rows]
        assert data['result']['rowCount'] >= 1  # fixture inserted a NULL-employee order

    def test_time_window_differential(self, client, connection):
        tpl = create_template(client)
        response = client.post(
            f"/api/templates/{tpl['id']}/instantiate",
            json={'values': {'countries': ['US', 'UK'],
                             'from_date': '2025-02-01',
                             'to_date': '2025-04-01',
                             'page_size': 10,
                             'page_offset': 0},
                  'execute': True})
        assert response.status_code == 200
        data = response.get_json()
        ref_columns, ref_rows = run_reference(
            connection,
            'SELECT c.first_name, o.total_amount FROM customer c '
            'LEFT JOIN "order" o ON c.id = o.customer_id '
            'WHERE c.country IN (:v1, :v2) '
            'AND o.order_date >= :d1 AND o.order_date < :d2 AND o.employee_id = :e '
            'LIMIT :lim',
            {'v1': 'US', 'v2': 'UK', 'd1': '2025-02-01', 'd2': '2025-04-01',
             'e': 1, 'lim': 10})
        assert [c['name'] for c in data['result']['columns']] == ref_columns
        assert [tuple(r) for r in data['result']['rows']] == [tuple(r) for r in ref_rows]

    def test_date_normalization(self):
        param = {'name': 'd', 'type': 'date', 'target': {'kind': 'where', 'nodeId': 'x'}}
        assert TemplateService.coerce_value(param, ' 2025-03-05 ') == '2025-03-05'


class TestSelfJoinTemplate:
    def test_self_join_references_and_results(self, client, connection):
        params = [
            {'id': 'p-left', 'name': 'left_country', 'type': 'string', 'required': True,
             'target': {'kind': 'where', 'nodeId': 'c1'}},
            {'id': 'p-right', 'name': 'right_country', 'type': 'string', 'required': True,
             'target': {'kind': 'where', 'nodeId': 'c2'}},
        ]
        tpl = create_template(client, name='self-join',
                              structure=self_join_structure(), parameters=params)
        response = client.post(
            f"/api/templates/{tpl['id']}/instantiate",
            json={'values': {'left_country': 'US', 'right_country': 'UK'},
                  'execute': True})
        assert response.status_code == 200
        data = response.get_json()
        # both table instances stay bound to their own aliases
        assert '"c"."country" = :p1' in data['sql']
        assert '"c2"."country" != :p2' in data['sql']
        ref_columns, ref_rows = run_reference(
            connection,
            'SELECT c.first_name, c2.city FROM customer c '
            'INNER JOIN customer c2 ON c.country = c2.country '
            "WHERE c.country = :v1 AND c2.country != :v2 LIMIT :lim",
            {'v1': 'US', 'v2': 'UK', 'lim': 100})
        from collections import Counter
        assert Counter(tuple(r) for r in data['result']['rows']) == Counter(tuple(r) for r in ref_rows)


# ----------------------------------------------------------------------
# Versioning / save / share / schema refresh
# ----------------------------------------------------------------------

class TestVersioningAndSharing:
    def test_version_bumps_only_on_structure_change(self, client):
        tpl = create_template(client)
        assert tpl['version'] == 1

        renamed = client.put(f"/api/templates/{tpl['id']}", json={'name': 'renamed'})
        assert renamed.get_json()['version'] == 1

        new_params = time_window_parameters() + [
            {'id': 'p-x', 'name': 'extra_limit', 'type': 'integer', 'required': False,
             'default': 5, 'target': {'kind': 'limit'}},
        ]
        updated = client.put(f"/api/templates/{tpl['id']}", json={'parameters': new_params})
        assert updated.get_json()['version'] == 2

    def test_template_survives_save_and_share(self, client):
        tpl = create_template(client)
        # reopen
        fetched = client.get(f"/api/templates/{tpl['id']}").get_json()
        assert fetched['query_structure']['tables'][0]['id'] == 't1'
        assert fetched['parameters'][0]['target']['nodeId'] == 'c1'

        # share restore keeps the exact same references
        token = client.post(f"/api/templates/{tpl['id']}/share", json={}).get_json()['token']
        shared = client.get(f'/api/share/template/{token}').get_json()['template']
        assert shared['query_structure'] == fetched['query_structure']
        assert shared['parameters'] == fetched['parameters']
        assert shared['version'] == fetched['version']

    def test_schema_refresh_keeps_stored_references(self, client, app):
        tpl = create_template(client)
        before = client.get(f"/api/templates/{tpl['id']}").get_json()
        with app.app_context():
            db.session.execute(text('ALTER TABLE customer RENAME COLUMN country TO country_old'))
            db.session.commit()
            try:
                # stored AST untouched by the schema refresh
                after = client.get(f"/api/templates/{tpl['id']}").get_json()
                assert after['query_structure'] == before['query_structure']

                # but instantiation now reports locatable migration errors
                response = client.post(f"/api/templates/{tpl['id']}/instantiate",
                                       json={'values': {'countries': ['US']}})
                assert response.status_code == 409
                payload = response.get_json()
                assert 'migration' in payload['error']
                missing = [i for i in payload['issues'] if i['code'] == 'COLUMN_MISSING']
                assert missing, payload['issues']
                assert any(i['column'] == 'country' and i['table'] == 'customer' for i in missing)
                # the parameterized clause is located by its path
                assert any("clause 'c1'" in i['path'] for i in missing)

                validation = client.get(f"/api/templates/{tpl['id']}/validate").get_json()
                assert validation['valid'] is False
                assert validation['issues'] == payload['issues']
            finally:
                db.session.execute(text('ALTER TABLE customer RENAME COLUMN country_old TO country'))
                db.session.commit()

        # after restoring the schema the template works again unchanged
        ok = client.post(f"/api/templates/{tpl['id']}/instantiate",
                         json={'values': {'countries': ['US']}})
        assert ok.status_code == 200

    def test_column_type_change_reports_migration_issue(self, client, app):
        with app.app_context():
            db.session.execute(text(
                'CREATE TABLE tmpl_scratch (id INTEGER PRIMARY KEY, amount INTEGER)'))
            db.session.commit()
        try:
            structure = {
                'tables': [{'id': 's1', 'tableName': 'tmpl_scratch', 'alias': 's'}],
                'joins': [],
                'selectedFields': [{'tableId': 's1', 'columnName': 'id'}],
                'where': {'id': 'w', 'op': 'AND', 'children': [
                    {'id': 'sc1', 'tableId': 's1', 'columnName': 'amount', 'cmp': '>', 'value': 0},
                ]},
                'aggregations': [], 'limit': 10, 'offset': 0,
            }
            params = [{'id': 'p-amt', 'name': 'min_amount', 'type': 'integer', 'required': True,
                       'target': {'kind': 'where', 'nodeId': 'sc1'}}]
            tpl = create_template(client, name='typed', structure=structure, parameters=params)

            with app.app_context():
                db.session.execute(text('DROP TABLE tmpl_scratch'))
                db.session.execute(text(
                    'CREATE TABLE tmpl_scratch (id INTEGER PRIMARY KEY, amount VARCHAR(50))'))
                db.session.commit()

            response = client.post(f"/api/templates/{tpl['id']}/instantiate",
                                   json={'values': {'min_amount': 5}})
            assert response.status_code == 409
            issues = response.get_json()['issues']
            changed = [i for i in issues if i['code'] == 'COLUMN_TYPE_CHANGED']
            assert changed, issues
            issue = changed[0]
            assert issue['parameter'] == 'min_amount'
            assert issue['column'] == 'amount'
            assert 'VARCHAR' in issue['actual']
            assert "parameters[0] ('min_amount')" in issue['path']
        finally:
            with app.app_context():
                db.session.execute(text('DROP TABLE IF EXISTS tmpl_scratch'))
                db.session.commit()


class TestCrud:
    def test_list_get_delete(self, client):
        tpl = create_template(client, name='crud')
        listed = client.get('/api/templates').get_json()
        assert any(t['id'] == tpl['id'] for t in listed)
        assert client.get(f"/api/templates/{tpl['id']}").status_code == 200
        assert client.delete(f"/api/templates/{tpl['id']}").status_code == 204
        assert client.get(f"/api/templates/{tpl['id']}").status_code == 404

    def test_invalid_ast_rejected_at_create(self, client):
        bad_structure = time_window_structure()
        bad_structure['tables'] = []
        response = client.post('/api/templates', json={
            'name': 'broken', 'parameters': [], 'query_structure': bad_structure})
        assert response.status_code == 400
