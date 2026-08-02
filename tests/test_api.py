"""API smoke tests via the Flask test client (no pre-started server needed)."""
import json


def customer_order_query():
    return {
        'tables': [
            {'id': 'c', 'tableName': 'customer', 'alias': 'c', 'position': {'x': 0, 'y': 0}},
            {'id': 'o', 'tableName': 'order', 'alias': 'o', 'position': {'x': 1, 'y': 0}},
        ],
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
                   'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'},
                           {'tableId': 'o', 'columnName': 'total_amount'}],
        'where': None, 'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 10,
    }


def test_metadata(client):
    resp = client.get('/api/metadata')
    assert resp.status_code == 200
    data = resp.get_json()
    names = {t['name'] for t in data}
    assert {'customer', 'order', 'product', 'employee'}.issubset(names)


def test_generate_sql(client):
    resp = client.post('/api/generate-sql', json=customer_order_query())
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'INNER JOIN' in data['sql']
    assert ':p' in data['sql']  # parameterized limit
    assert isinstance(data['params'], dict)


def test_execute_query(client):
    resp = client.post('/api/execute-query', json=customer_order_query())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['rowCount'] >= 1
    assert data['columns'][0]['name'] == 'country'
    assert 'truncated' in data


def test_explain_uses_same_sql(client):
    q = customer_order_query()
    gen = client.post('/api/generate-sql', json=q).get_json()
    exp = client.post('/api/explain', json=q).get_json()
    assert exp['sql'] == gen['sql']
    assert 'queryPlan' in exp


def test_right_join_rejected_api(client):
    q = customer_order_query()
    q['joins'][0]['type'] = 'RIGHT'
    resp = client.post('/api/generate-sql', json=q)
    assert resp.status_code == 400
    assert 'RIGHT' in resp.get_json()['error']


def test_save_share_execute_flow(client):
    q = customer_order_query()
    created = client.post('/api/queries', json={
        'name': 'smoke', 'description': 'd', 'query_structure': q,
    })
    assert created.status_code == 201
    qid = created.get_json()['id']

    share = client.post(f'/api/queries/{qid}/share', json={'expires_in_hours': 1})
    assert share.status_code == 200
    token = share.get_json()['token']

    shared = client.get(f'/api/share/{token}')
    assert shared.status_code == 200
    body = shared.get_json()
    # Restored share executes the same AST and returns rows.
    assert body['result']['rowCount'] >= 1
    assert body['query']['query_structure']['joins'][0]['type'] == 'INNER'
