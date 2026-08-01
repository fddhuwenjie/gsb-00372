"""API smoke tests via the Flask test client: no pre-started server needed.
Covers metadata, SQL generation, execution, EXPLAIN parity, saved-query CRUD,
share/restore flow, history, and rejection of unsupported JOIN types.
"""
import pytest


def two_table_query(**overrides):
    query = {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c',
             'position': {'x': 100, 'y': 100}},
            {'id': 't2', 'tableName': 'order', 'alias': 'o',
             'position': {'x': 400, 'y': 100}},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'id',
             'rightTableId': 't2', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't1', 'columnName': 'country'},
            {'tableId': 't2', 'columnName': 'total_amount'},
        ],
        'where': {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't2', 'columnName': 'total_amount', 'cmp': '>', 'value': 100},
                {'id': 'g1', 'op': 'OR', 'children': [
                    {'id': 'c2', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                    {'id': 'c3', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'UK'},
                ]},
            ],
        },
        'aggregations': [],
        'limit': 10,
    }
    query.update(overrides)
    return query


class TestMetadata:
    def test_metadata_lists_business_tables(self, client):
        response = client.get('/api/metadata')
        assert response.status_code == 200
        tables = {t['name']: t for t in response.get_json()}
        for name in ('customer', 'order', 'order_item', 'product', 'category', 'supplier', 'employee'):
            assert name in tables
        order = tables['order']
        fk_targets = {fk['toTable'] for fk in order['foreignKeys']}
        assert 'customer' in fk_targets


class TestGenerateSql:
    def test_sql_and_params_are_separated(self, client):
        response = client.post('/api/generate-sql', json=two_table_query())
        assert response.status_code == 200
        data = response.get_json()
        assert 'INNER JOIN' in data['sql']
        assert ':p' in data['sql']
        assert data['params'] == {'p1': 100, 'p2': 'US', 'p3': 'UK', 'p4': 10}
        # no user value is inlined into the SQL text
        assert 'US' not in data['sql']
        assert '100' not in data['sql']

    def test_invalid_ast_returns_400(self, client):
        response = client.post('/api/generate-sql', json={'tables': []})
        assert response.status_code == 400
        assert 'error' in response.get_json()

    @pytest.mark.parametrize('join_type', ['RIGHT', 'FULL'])
    def test_unsupported_join_types_rejected(self, client, join_type):
        query = two_table_query()
        query['joins'][0]['type'] = join_type
        response = client.post('/api/generate-sql', json=query)
        assert response.status_code == 400
        assert 'not supported by SQLite' in response.get_json()['error']


class TestExecuteAndExplain:
    def test_execute_query(self, client):
        response = client.post('/api/execute-query', json=two_table_query(),
                               headers={'X-Session-Id': 'api-smoke'})
        assert response.status_code == 200
        data = response.get_json()
        assert data['rowCount'] > 0
        assert [c['name'] for c in data['columns']] == ['first_name', 'country', 'total_amount']
        assert data['truncated'] is False
        assert data['params']['p1'] == 100

    def test_explain_matches_execute_sql_and_params(self, client):
        query = two_table_query()
        executed = client.post('/api/execute-query', json=query).get_json()
        explained = client.post('/api/explain', json=query).get_json()
        assert explained['sql'] == executed['sql']
        assert explained['params'] == executed['params']
        assert len(explained['queryPlan']['nodes']) >= 2

    def test_history_recorded_for_session(self, client):
        client.post('/api/execute-query', json=two_table_query(),
                    headers={'X-Session-Id': 'history-smoke'})
        response = client.get('/api/history', headers={'X-Session-Id': 'history-smoke'})
        assert response.status_code == 200
        history = response.get_json()
        assert len(history) >= 1
        assert history[0]['query_structure']['tables'][0]['alias'] == 'c'
        assert history[0]['params']

    def test_cancel_endpoint(self, client):
        response = client.post('/api/cancel-query', headers={'X-Session-Id': 'api-smoke'})
        assert response.status_code == 200
        assert response.get_json()['cancelled'] is True


class TestSavedQueries:
    def test_crud_and_restore_roundtrip(self, client):
        created = client.post('/api/queries', json={
            'name': 'Smoke query',
            'description': 'created by smoke test',
            'query_structure': two_table_query(),
        })
        assert created.status_code == 201
        saved = created.get_json()
        assert saved['id']

        fetched = client.get(f"/api/queries/{saved['id']}")
        assert fetched.status_code == 200
        restored = fetched.get_json()['query_structure']
        # stable ids/aliases survive the save/reopen round trip
        assert restored['tables'][0]['id'] == 't1'
        assert restored['tables'][0]['alias'] == 'c'
        assert restored['joins'][0]['leftTableId'] == 't1'

        updated = client.put(f"/api/queries/{saved['id']}", json={'name': 'Renamed'})
        assert updated.status_code == 200
        assert updated.get_json()['name'] == 'Renamed'

        listed = client.get('/api/queries')
        assert any(q['id'] == saved['id'] for q in listed.get_json())

        deleted = client.delete(f"/api/queries/{saved['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/queries/{saved['id']}").status_code == 404

    def test_share_and_restore(self, client):
        saved = client.post('/api/queries', json={
            'name': 'Share me',
            'query_structure': two_table_query(),
        }).get_json()

        shared = client.post(f"/api/queries/{saved['id']}/share", json={'expires_in_hours': 1})
        assert shared.status_code == 200
        token = shared.get_json()['token']

        restored = client.get(f'/api/share/{token}')
        assert restored.status_code == 200
        payload = restored.get_json()
        assert payload['query']['query_structure']['tables'][0]['id'] == 't1'
        assert payload['result']['rowCount'] > 0

    def test_export_sql(self, client):
        saved = client.post('/api/queries', json={
            'name': 'Export me',
            'query_structure': two_table_query(),
        }).get_json()
        response = client.get(f"/api/queries/{saved['id']}/export")
        assert response.status_code == 200
        assert 'SELECT' in response.get_data(as_text=True)


class TestOpenApi:
    def test_openapi_spec_available(self, client):
        response = client.get('/api/openapi.json')
        assert response.status_code == 200
        assert response.get_json()['info']['title'] == 'Visual Query Builder API'
