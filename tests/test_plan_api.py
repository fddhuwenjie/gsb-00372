"""API tests for execution-plan capture and version comparison."""


def base_query():
    return {
        'tables': [
            {'id': 'o', 'tableName': 'order', 'alias': 'o', 'position': {}},
            {'id': 'c', 'tableName': 'customer', 'alias': 'c', 'position': {}},
        ],
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
                   'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'd1', 'tableId': 'o', 'columnName': 'total_amount', 'cmp': '>=', 'value': 0}]},
        'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100, 'offset': 0,
    }


def make_template_with_two_versions(client):
    param = client.post('/api/templates/parameterize', json={
        'query_structure': base_query(),
        'specs': [{'name': 'min_total', 'type': 'number', 'required': True,
                   'target': {'kind': 'filter', 'clauseId': 'd1'}}],
    }).get_json()
    tid = client.post('/api/templates', json={
        'name': 'plan-cmp', 'query_structure': param['queryStructure'], 'parameters': param['parameters'],
    }).get_json()['id']
    # v2: switch the join to LEFT (real semantic change).
    v2 = dict(param['queryStructure'])
    v2['joins'] = [{**v2['joins'][0], 'type': 'LEFT'}]
    client.put(f'/api/templates/{tid}', json={'query_structure': v2, 'parameters': param['parameters']})
    return tid


def test_record_plan_stores_types_not_values(client):
    tid = make_template_with_two_versions(client)
    resp = client.post(f'/api/templates/{tid}/plan-record', json={
        'version': 1, 'values': {'min_total': 12345.67},
    })
    assert resp.status_code == 201
    rec = resp.get_json()
    assert rec['ast_hash']
    assert '12345.67' not in str(rec['raw_plan'])
    assert rec['param_type_summary']['count'] >= 1
    assert rec['normalized_plan']['accesses']


def test_compare_versions_locates_join_change(client):
    tid = make_template_with_two_versions(client)
    resp = client.post(f'/api/templates/{tid}/compare-plans', json={
        'versionA': 1, 'versionB': 2, 'values': {'min_total': 100},
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['semanticallyEqual'] is False
    joins = [c for c in body['astChanges'] if c['kind'] == 'join']
    assert joins and joins[0]['change'] == 'modified'
    assert 'rowCountDelta' in body['result']
    # types only, never a raw value
    assert '100' not in str(body['paramTypeSummaryA'])


def test_compare_same_version_no_changes(client):
    tid = make_template_with_two_versions(client)
    resp = client.post(f'/api/templates/{tid}/compare-plans', json={
        'versionA': 1, 'versionB': 1, 'values': {'min_total': 100},
    })
    body = resp.get_json()
    assert body['semanticallyEqual'] is True
    assert body['changeCount'] == 0


def test_list_plan_records(client):
    tid = make_template_with_two_versions(client)
    client.post(f'/api/templates/{tid}/plan-record', json={'version': 1, 'values': {'min_total': 1}})
    client.post(f'/api/templates/{tid}/plan-record', json={'version': 2, 'values': {'min_total': 1}})
    all_records = client.get(f'/api/templates/{tid}/plan-records').get_json()
    assert len(all_records) >= 2
    v1_only = client.get(f'/api/templates/{tid}/plan-records?version=1').get_json()
    assert all(r['template_version'] == 1 for r in v1_only)
