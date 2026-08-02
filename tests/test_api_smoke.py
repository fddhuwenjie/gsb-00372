"""
API smoke test -- runs the Flask app via its test client against a temporary
SQLite database. No external server process is required.

Run from the repository root:
    pytest tests/test_api_smoke.py -v
"""
import json


def test_metadata_endpoint(client):
    resp = client.get('/api/metadata')
    assert resp.status_code == 200
    tables = resp.get_json()
    names = {t['name'] for t in tables}
    assert {'customer', 'order', 'product', 'category'}.issubset(names)
    order_table = next(t for t in tables if t['name'] == 'order')
    assert any(col['name'] == 'customer_id' for col in order_table['columns'])


def test_generate_sql_endpoint(client):
    qs = {
        'tables': [
            {'id': 'c', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'o', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [{
            'id': 'j', 'type': 'INNER',
            'leftTableId': 'c', 'leftColumn': 'id',
            'rightTableId': 'o', 'rightColumn': 'customer_id',
            'leftTable': 'customer', 'rightTable': 'order',
        }],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'country'},
        ],
        'where': None,
        'aggregations': [
            {'tableId': 'o', 'columnName': 'total_amount',
             'function': 'SUM', 'alias': 'total'},
        ],
        'limit': 10,
    }
    resp = client.post('/api/generate-sql', json=qs)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert 'SUM(' in body['sql']
    assert 'LIMIT :' in body['sql']
    assert isinstance(body['params'], dict)


def test_execute_query_endpoint(client):
    qs = {
        'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'id'},
            {'tableId': 'c', 'columnName': 'country'},
        ],
        'where': {
            'tableId': 'c', 'columnName': 'country',
            'cmp': 'IN', 'value': ['US', 'UK'],
        },
        'aggregations': [],
        'limit': 50,
    }
    resp = client.post('/api/execute-query', json=qs)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['rowCount'] >= 1
    for row in body['rows']:
        assert row[1] in ('US', 'UK')


def test_explain_endpoint(client):
    qs = {
        'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': None,
        'aggregations': [],
        'limit': 5,
    }
    resp = client.post('/api/explain', json=qs)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert 'queryPlan' in body
    assert 'bytecode' in body
    # EXPLAIN must use the same compiled SQL/params as execution
    assert body['sql'].startswith('SELECT')


def test_right_join_rejected_via_api(client):
    qs = {
        'tables': [
            {'id': 'c', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'o', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [{
            'id': 'j', 'type': 'RIGHT',
            'leftTableId': 'c', 'leftColumn': 'id',
            'rightTableId': 'o', 'rightColumn': 'customer_id',
            'leftTable': 'customer', 'rightTable': 'order',
        }],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': None,
        'aggregations': [],
        'limit': 5,
    }
    resp = client.post('/api/execute-query', json=qs)
    assert resp.status_code == 400
    assert 'not supported by SQLite' in resp.get_json()['error']


def test_saved_query_crud_and_share(client):
    qs = {
        'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': None,
        'aggregations': [],
        'limit': 5,
    }
    create = client.post('/api/queries', json={
        'name': 'Smoke Query',
        'description': 'created by smoke test',
        'query_structure': qs,
    })
    assert create.status_code == 201, create.get_data(as_text=True)
    saved = create.get_json()
    qid = saved['id']

    listed = client.get('/api/queries')
    assert listed.status_code == 200
    assert any(q['id'] == qid for q in listed.get_json())

    share = client.post(f'/api/queries/{qid}/share', json={'expires_in_hours': 1})
    assert share.status_code == 200
    token = share.get_json()['token']

    shared = client.get(f'/api/share/{token}')
    assert shared.status_code == 200
    assert shared.get_json()['result']['rowCount'] >= 1

    delete = client.delete(f'/api/queries/{qid}')
    assert delete.status_code == 204


def test_history_recorded(client):
    qs = {
        'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': None,
        'aggregations': [],
        'limit': 3,
    }
    client.post('/api/execute-query', json=qs, headers={'X-Session-Id': 'smoke-session'})
    resp = client.get('/api/history', headers={'X-Session-Id': 'smoke-session'})
    assert resp.status_code == 200
    history = resp.get_json()
    assert len(history) >= 1
    assert history[0]['sql'].startswith('SELECT')
