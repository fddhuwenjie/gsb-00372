"""Execution-plan comparison tests on the fixed database fixture.

Proves:
- non-semantic formatting changes (key order, table/clause array order,
  node ids, parameter values, canvas positions) never create version
  differences — same AST hash, empty change set;
- real JOIN / filter changes produce a stable, deterministic change set
  localized to AST nodes;
- snapshots record AST hash + parameter *type* summary + normalized EXPLAIN
  plan + duration + row count, never raw parameter values.
"""
import json

import pytest
from sqlalchemy import text

from app.database import db
from app.services.plan_service import (
    ast_hash, params_summary, normalize_explain_plan,
    diff_query_structures, diff_plans, canonicalize_query,
)
from app.services.query_executor import QueryExecutor
from tests.test_templates import time_window_structure, time_window_parameters, create_template


def base_structure():
    return time_window_structure()


# ----------------------------------------------------------------------
# AST hash stability (non-semantic formatting)
# ----------------------------------------------------------------------

class TestAstHashStability:
    def test_key_order_and_whitespace_do_not_change_hash(self):
        a = base_structure()
        b = json.loads(json.dumps(a))  # re-serialized copy
        # rebuild with keys inserted in a different order
        reordered = {
            'limit': b['limit'],
            'where': b['where'],
            'aggregations': b['aggregations'],
            'selectedFields': b['selectedFields'],
            'joins': b['joins'],
            'tables': b['tables'],
            'offset': 0,
        }
        assert ast_hash(a) == ast_hash(reordered)

    def test_table_and_join_array_order_do_not_change_hash(self):
        a = base_structure()
        b = base_structure()
        b['tables'] = list(reversed(b['tables']))
        b['joins'] = list(reversed(b['joins']))
        b['selectedFields'] = list(reversed(b['selectedFields']))
        assert ast_hash(a) == ast_hash(b)

    def test_condition_children_order_does_not_change_hash(self):
        a = base_structure()
        b = base_structure()
        b['where']['children'] = list(reversed(b['where']['children']))
        assert ast_hash(a) == ast_hash(b)

    def test_node_ids_do_not_change_hash(self):
        a = base_structure()
        b = base_structure()
        b['tables'][0]['id'] = 'different-id-1'
        b['tables'][1]['id'] = 'different-id-2'
        b['joins'][0]['id'] = 'different-join'
        b['joins'][0]['leftTableId'] = 'different-id-1'
        b['joins'][0]['rightTableId'] = 'different-id-2'
        b['selectedFields'][0]['tableId'] = 'different-id-1'
        b['selectedFields'][1]['tableId'] = 'different-id-2'
        for i, child in enumerate(b['where']['children']):
            child['id'] = f'renamed-{i}'
            child['tableId'] = 'different-id-2' if child['tableId'] == 't2' else 'different-id-1'
        assert ast_hash(a) == ast_hash(b)

    def test_parameter_values_do_not_change_hash(self):
        a = base_structure()
        b = base_structure()
        b['where']['children'][0]['value'] = ['TOTALLY', 'DIFFERENT']
        b['where']['children'][1]['value'] = '1999-01-01'
        b['limit'] = 7
        b['offset'] = 42
        assert ast_hash(a) == ast_hash(b)

    def test_canvas_positions_do_not_change_hash(self):
        a = base_structure()
        b = base_structure()
        b['tables'][0]['position'] = {'x': 999, 'y': 999}
        assert ast_hash(a) == ast_hash(b)


class TestAstHashSemanticChanges:
    def test_join_type_change_changes_hash(self):
        a = base_structure()
        b = base_structure()
        b['joins'][0]['type'] = 'INNER'
        assert ast_hash(a) != ast_hash(b)

    def test_added_filter_changes_hash(self):
        a = base_structure()
        b = base_structure()
        b['where']['children'].append(
            {'id': 'c9', 'tableId': 't2', 'columnName': 'status', 'cmp': '=', 'value': 'x'})
        assert ast_hash(a) != ast_hash(b)

    def test_operator_change_changes_hash(self):
        a = base_structure()
        b = base_structure()
        b['where']['children'][1]['cmp'] = '>'
        assert ast_hash(a) != ast_hash(b)

    def test_selected_field_change_changes_hash(self):
        a = base_structure()
        b = base_structure()
        b['selectedFields'].append({'tableId': 't1', 'columnName': 'country'})
        assert ast_hash(a) != ast_hash(b)

    def test_aggregation_change_changes_hash(self):
        a = base_structure()
        b = base_structure()
        b['aggregations'] = [{'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM'}]
        assert ast_hash(a) != ast_hash(b)


# ----------------------------------------------------------------------
# Params summary
# ----------------------------------------------------------------------

class TestParamsSummary:
    def test_type_tags_only(self):
        summary = params_summary({'p1': 'UK', 'p2': 5, 'p3': 2.5, 'p4': True,
                                  'p5': None, 'p6': ['a', 'b']})
        assert summary == {'p1': 'string', 'p2': 'integer', 'p3': 'number',
                           'p4': 'boolean', 'p5': 'null', 'p6': 'string[]'}
        # no raw values anywhere
        assert 'UK' not in json.dumps(summary)
        assert '5' not in json.dumps(summary).replace('p5', '')


# ----------------------------------------------------------------------
# Plan normalization (fixed DB fixture)
# ----------------------------------------------------------------------

def explain_normalized(app, query):
    with app.app_context():
        result = QueryExecutor.generate_sql(query)
        with db.engine.connect() as connection:
            rows = connection.execute(
                text(f'EXPLAIN QUERY PLAN {result["sql"]}'), result['params']).fetchall()
    return normalize_explain_plan([tuple(r) for r in rows],
                                  QueryExecutor._alias_map(query))


class TestPlanNormalization:
    def test_scan_normalized_to_table_access(self, app):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'first_name'}],
            'where': None, 'aggregations': [], 'limit': 10,
        }
        plan = explain_normalized(app, query)
        assert plan['nodes'] == [
            {'op': 'SCAN', 'table': 'customer', 'alias': 'c',
             'index': None, 'using': None, 'access': 'full-scan'}
        ]

    def test_covering_index_scan_is_classified(self, app):
        # selecting only the PK is served by the autoindex covering index
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'aggregations': [], 'limit': 10,
        }
        plan = explain_normalized(app, query)
        assert plan['nodes'][0]['access'] == 'covering-index'
        assert plan['nodes'][0]['table'] == 'customer'

    def test_alias_formatting_does_not_change_normalized_plan(self, app):
        def query_with_alias(alias):
            return {
                'tables': [
                    {'id': 't1', 'tableName': 'customer', 'alias': alias},
                    {'id': 't2', 'tableName': 'order', 'alias': 'x1'},
                ],
                'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 't1',
                           'leftColumn': 'id', 'rightTableId': 't2',
                           'rightColumn': 'customer_id',
                           'leftTable': 'customer', 'rightTable': 'order'}],
                'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
                'where': None, 'aggregations': [], 'limit': 10,
            }
        plan_a = explain_normalized(app, query_with_alias('c'))
        plan_b = explain_normalized(app, query_with_alias('totally_different'))
        # table-level accesses are identical; only alias labels differ
        assert [(n['table'], n['op'], n['access']) for n in plan_a['nodes']] == \
               [(n['table'], n['op'], n['access']) for n in plan_b['nodes']]

    def test_index_creation_is_detected_as_plan_change(self, app):
        query = {
            'tables': [{'id': 't1', 'tableName': 'order', 'alias': 'o'}],
            'joins': [],
            # selecting a non-indexed column forces a real (non-covering)
            # index lookup once the index exists
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'total_amount'},
            ],
            'where': {'id': 'w', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'status', 'cmp': '=', 'value': 'pending'},
            ]},
            'aggregations': [], 'limit': 10,
        }
        plan_before = explain_normalized(app, query)
        assert plan_before['nodes'][0]['access'] == 'full-scan'

        def run_ddl(sql):
            with app.app_context():
                ddl = db.engine.connect()
                ddl.execute(text(sql))
                ddl.commit()
                ddl.close()
                # schema refresh boundary: pooled connections may serve stale
                # plans after DDL, so drop them (mirrors a real refresh)
                db.engine.dispose()

        run_ddl('CREATE INDEX idx_order_status ON "order"(status)')
        try:
            plan_after = explain_normalized(app, query)
            node = plan_after['nodes'][0]
            assert node['access'] == 'index'
            assert node['index'] == 'idx_order_status'

            changes = diff_plans(plan_before, plan_after)
            assert changes == [{
                'category': 'access-path', 'change': 'modified',
                'table': 'order', 'alias': 'o',
                'detail': {
                    'from': {'op': 'SCAN', 'access': 'full-scan', 'index': None},
                    'to': {'op': 'SEARCH', 'access': 'index', 'index': 'idx_order_status'},
                },
            }]
        finally:
            run_ddl('DROP INDEX IF EXISTS idx_order_status')


# ----------------------------------------------------------------------
# Execution snapshots
# ----------------------------------------------------------------------

class TestSnapshots:
    def test_snapshot_records_hash_summary_plan_without_raw_values(self, client):
        secret = 'United-Kingdom-Secret-7'
        query = time_window_structure()
        query['where']['children'][0]['value'] = [secret]
        response = client.post('/api/execute-query', json=query,
                               headers={'X-Session-Id': 'snap-test'})
        assert response.status_code == 200

        snapshots = client.get('/api/executions').get_json()
        assert len(snapshots) >= 1
        snap = snapshots[0]
        assert snap['ast_hash']
        assert snap['ast_hash'] == ast_hash(query)
        assert snap['params_summary']['p1'] == 'string'
        assert snap['plan_json']['nodes']
        assert snap['row_count'] >= 0
        assert snap['duration_ms'] >= 0
        # the sensitive value must not appear anywhere in the snapshot
        assert secret not in json.dumps(snap)
        assert 'sql' not in snap

    def test_same_query_different_values_share_ast_hash(self, client):
        query = time_window_structure()
        query['where']['children'][0]['value'] = ['US']
        client.post('/api/execute-query', json=query, headers={'X-Session-Id': 'snap-2'})
        query['where']['children'][0]['value'] = ['UK', 'Germany']
        client.post('/api/execute-query', json=query, headers={'X-Session-Id': 'snap-2'})
        snapshots = client.get('/api/executions?limit=2').get_json()
        assert snapshots[0]['ast_hash'] == snapshots[1]['ast_hash']

    def test_template_execution_snapshot_has_template_context(self, client):
        tpl = create_template(client, name='snap-tpl')
        client.post(f"/api/templates/{tpl['id']}/instantiate",
                    json={'values': {'countries': ['US']}, 'execute': True})
        snapshots = client.get(f"/api/executions?template_id={tpl['id']}").get_json()
        assert len(snapshots) == 1
        assert snapshots[0]['template_version'] == tpl['version']


# ----------------------------------------------------------------------
# Template version comparison
# ----------------------------------------------------------------------

class TestVersionCompare:
    def test_versions_archived(self, client):
        tpl = create_template(client, name='versions')
        versions = client.get(f"/api/templates/{tpl['id']}/versions").get_json()
        assert [v['version'] for v in versions] == [1]

        new_structure = time_window_structure()
        new_structure['joins'][0]['type'] = 'INNER'
        client.put(f"/api/templates/{tpl['id']}",
                   json={'query_structure': new_structure})
        versions = client.get(f"/api/templates/{tpl['id']}/versions").get_json()
        assert [v['version'] for v in versions] == [1, 2]

    def test_formatting_only_change_produces_empty_change_set(self, client):
        tpl = create_template(client, name='fmt')
        # v2: formatting-only — reversed arrays, reordered children, positions
        fmt = time_window_structure()
        fmt['tables'] = list(reversed(fmt['tables']))
        fmt['where']['children'] = list(reversed(fmt['where']['children']))
        fmt['tables'][0]['position'] = {'x': 1, 'y': 2}
        put = client.put(f"/api/templates/{tpl['id']}", json={'query_structure': fmt})
        assert put.get_json()['version'] == 2

        compare = client.post(f"/api/templates/{tpl['id']}/compare",
                              json={'from_version': 1, 'to_version': 2,
                                    'values': {'countries': ['US']},
                                    'include_results': True})
        assert compare.status_code == 200
        data = compare.get_json()
        assert data['ast_hash_from'] == data['ast_hash_to']
        assert data['ast_changes'] == []
        assert data['plan_changes'] == []
        assert data['result_diff']['rows_from'] == data['result_diff']['rows_to']
        assert data['result_diff']['rows_only_in_from'] == 0
        assert data['result_diff']['rows_only_in_to'] == 0

    def test_semantic_changes_produce_stable_change_set(self, client):
        tpl = create_template(client, name='semantic')

        changed = time_window_structure()
        changed['joins'][0]['type'] = 'INNER'                    # JOIN change
        changed['where']['children'][1]['cmp'] = '>'             # filter operator change
        changed['where']['children'].append(                     # filter added
            {'id': 'c9', 'tableId': 't2', 'columnName': 'status', 'cmp': '=', 'value': 'pending'})
        changed['aggregations'] = [                              # aggregation added
            {'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM', 'alias': 'total'}]
        put = client.put(f"/api/templates/{tpl['id']}", json={'query_structure': changed})
        assert put.get_json()['version'] == 2

        payload = {'from_version': 1, 'to_version': 2,
                   'values': {'countries': ['US']}, 'include_results': True}
        first = client.post(f"/api/templates/{tpl['id']}/compare", json=payload).get_json()
        second = client.post(f"/api/templates/{tpl['id']}/compare", json=payload).get_json()

        # deterministic change set across runs
        assert first['ast_changes'] == second['ast_changes']
        assert first['ast_hash_from'] != first['ast_hash_to']

        changes = first['ast_changes']

        join_changes = [c for c in changes if c['category'] == 'join']
        assert join_changes == [{
            'category': 'join', 'change': 'modified',
            'nodeId': 'j1', 'label': 'c.id = o.customer_id',
            'detail': {'from': 'LEFT', 'to': 'INNER'},
        }]

        filter_changes = [c for c in changes if c['category'] == 'filter']
        assert {
            (c['change'], c['nodeId'], c.get('detail', {}).get('from'), c.get('detail', {}).get('to'))
            for c in filter_changes
        } == {
            ('modified', 'c2', '>=', '>'),
            ('added', 'c9', None, None),
        }

        agg_changes = [c for c in changes if c['category'] == 'aggregation']
        assert len(agg_changes) == 1
        assert agg_changes[0]['change'] == 'added'
        assert 'SUM(o.total_amount)' in agg_changes[0]['label']

        # every change is localized to an AST node id, never a SQL line number
        for change in changes:
            assert 'line' not in json.dumps(change).lower()

        # result differences are real row-level comparisons
        diff = first['result_diff']
        assert diff['rows_from'] != diff['rows_to'] or \
            diff['rows_only_in_from'] != diff['rows_only_in_to']

    def test_compare_rejects_unknown_version(self, client):
        tpl = create_template(client, name='unknown-version')
        response = client.post(f"/api/templates/{tpl['id']}/compare",
                               json={'from_version': 99})
        assert response.status_code == 404

    def test_diff_query_structures_ignores_values(self):
        a = time_window_structure()
        b = time_window_structure()
        b['where']['children'][0]['value'] = ['DIFFERENT']
        b['limit'] = 5
        assert diff_query_structures(a, b) == [
            {'category': 'pagination', 'change': 'modified', 'nodeId': None,
             'label': 'limit', 'detail': {'from': 100, 'to': 5}},
        ]
