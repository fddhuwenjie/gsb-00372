"""Template API tests via the Flask test client.

Each instantiated template is compared against equivalent hand-written
parameterized SQL run directly on the same SQLite database (differential),
plus versioning, share restore and schema-migration surfacing.
"""


def base_query():
    return {
        'tables': [
            {'id': 'o', 'tableName': 'order', 'alias': 'o', 'position': {}},
            {'id': 'c', 'tableName': 'customer', 'alias': 'c', 'position': {}},
        ],
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
                   'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'},
                           {'tableId': 'o', 'columnName': 'total_amount'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'd1', 'tableId': 'o', 'columnName': 'total_amount', 'cmp': '>=', 'value': 0},
            {'id': 'ct', 'tableId': 'c', 'columnName': 'country', 'cmp': 'IN', 'value': ['US']}]},
        'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100, 'offset': 0,
    }


def create_template(client, name='tpl'):
    param = client.post('/api/templates/parameterize', json={
        'query_structure': base_query(),
        'specs': [
            {'name': 'min_total', 'type': 'number', 'required': True,
             'target': {'kind': 'filter', 'clauseId': 'd1'}},
            {'name': 'countries', 'type': 'list', 'itemType': 'string', 'default': ['US'],
             'target': {'kind': 'filter', 'clauseId': 'ct'}},
            {'name': 'page_size', 'type': 'integer', 'default': 25,
             'target': {'kind': 'limit'}},
        ],
    }).get_json()
    created = client.post('/api/templates', json={
        'name': name, 'query_structure': param['queryStructure'], 'parameters': param['parameters'],
    })
    return created


def ref_rows(conn, sql, params):
    cur = conn.execute(sql, params)
    return [list(r) for r in cur.fetchall()]


def test_create_lists_and_versions(client):
    created = create_template(client)
    assert created.status_code == 201
    body = created.get_json()
    assert body['current_version'] == 1
    assert len(body['versions']) == 1
    listing = client.get('/api/templates').get_json()
    assert any(t['id'] == body['id'] for t in listing)


def test_instantiate_differential(client, sqlite_conn):
    tid = create_template(client).get_json()['id']
    resp = client.post(f'/api/templates/{tid}/instantiate', json={
        'values': {'min_total': 100, 'countries': ['US', 'UK']},
    })
    assert resp.status_code == 200
    gen_rows = resp.get_json()['rows']

    ref = ('SELECT c.country, o.total_amount FROM "order" o '
           'INNER JOIN customer c ON o.customer_id = c.id '
           'WHERE o.total_amount >= :p1 AND c.country IN (:p2, :p3) '
           'ORDER BY o.id ASC LIMIT :p4')
    expected = ref_rows(sqlite_conn, ref, {'p1': 100, 'p2': 'US', 'p3': 'UK', 'p4': 25})
    assert gen_rows == expected


def test_instantiate_sql_mode_is_parameterized(client):
    tid = create_template(client).get_json()['id']
    resp = client.post(f'/api/templates/{tid}/instantiate', json={
        'mode': 'sql', 'values': {'min_total': 50, 'countries': ['US']},
    })
    data = resp.get_json()
    assert ':p' in data['sql']
    # SQL text has no raw literal; values live only in params.
    assert '50' not in data['sql']
    assert 50 in data['params'].values()


def test_empty_in_list_differential(client, sqlite_conn):
    tid = create_template(client).get_json()['id']
    resp = client.post(f'/api/templates/{tid}/instantiate', json={
        'values': {'min_total': 0, 'countries': []},
    })
    assert resp.status_code == 200
    # empty IN -> no country matches
    assert resp.get_json()['rowCount'] == 0


def test_required_and_type_errors(client):
    tid = create_template(client).get_json()['id']
    miss = client.post(f'/api/templates/{tid}/instantiate', json={'values': {'countries': ['US']}})
    assert miss.status_code == 400
    assert 'min_total' in miss.get_json()['error']

    bad = client.post(f'/api/templates/{tid}/instantiate', json={'values': {'min_total': 'x'}})
    assert bad.status_code == 400


def test_versioning_old_version_still_instantiable(client):
    created = create_template(client).get_json()
    tid = created['id']
    # Change the definition (add offset param) -> version bumps to 2.
    new_qs = dict(created['query_structure'])
    new_qs['offset'] = {'$param': 'page_offset'}
    new_params = created['parameters'] + [
        {'name': 'page_offset', 'type': 'integer', 'default': 0}
    ]
    updated = client.put(f'/api/templates/{tid}', json={
        'query_structure': new_qs, 'parameters': new_params,
    }).get_json()
    assert updated['current_version'] == 2

    # v1 still works with its original parameter set.
    v1 = client.post(f'/api/templates/{tid}/instantiate', json={
        'version': 1, 'mode': 'sql', 'values': {'min_total': 10, 'countries': ['US']},
    })
    assert v1.status_code == 200
    # v2 accepts the new offset param.
    v2 = client.post(f'/api/templates/{tid}/instantiate', json={
        'version': 2, 'mode': 'sql', 'values': {'min_total': 10, 'countries': ['US'], 'page_offset': 5},
    })
    assert v2.status_code == 200
    assert 5 in v2.get_json()['params'].values()


def test_share_restore_roundtrip(client):
    tid = create_template(client).get_json()['id']
    share = client.post(f'/api/templates/{tid}/share', json={'expires_in_hours': 1})
    assert share.status_code == 200
    token = share.get_json()['token']
    shared = client.get(f'/api/template-share/{token}')
    assert shared.status_code == 200
    tpl = shared.get_json()['template']
    assert {p['name'] for p in tpl['parameters']} == {'min_total', 'countries', 'page_size'}


def test_check_schema_ok(client):
    tid = create_template(client).get_json()['id']
    resp = client.get(f'/api/templates/{tid}/check-schema')
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True


def test_explain_mode_uses_same_ast(client):
    tid = create_template(client).get_json()['id']
    sql_resp = client.post(f'/api/templates/{tid}/instantiate', json={
        'mode': 'sql', 'values': {'min_total': 10, 'countries': ['US']},
    }).get_json()
    exp_resp = client.post(f'/api/templates/{tid}/instantiate', json={
        'mode': 'explain', 'values': {'min_total': 10, 'countries': ['US']},
    }).get_json()
    assert exp_resp['sql'] == sql_resp['sql']
    assert 'queryPlan' in exp_resp
