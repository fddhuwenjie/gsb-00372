"""
Plan normalization and structural diff tests.

Core guarantees tested here:
1. AST hash is canonical: non-semantic changes (node IDs, positions,
   whitespace, parameter VALUES) do not change the hash.
2. Plan normalization maps SQLite EXPLAIN QUERY PLAN output to AST node IDs,
   not SQL line numbers.
3. Identical semantic queries produce identical normalized operations and
   empty diffs even when ephemeral IDs differ.
4. Real structural changes (JOIN type, filter addition/removal, aggregation)
   produce a stable change set keyed by AST node references.
5. Parameter type summary never contains values.
6. Snapshot persistence and API comparison work end-to-end.
"""
import copy
import pytest
from sqlalchemy import text
from app.services.plan_service import (
    compute_ast_hash, compute_param_type_summary,
    normalize_explain_plan, diff_plans, create_snapshot,
    _operation_fingerprint,
)
from app.services.sql_generator import SQLGenerator
from app.models import PlanSnapshot, db as _db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_query():
    return {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [{
            'id': 'j1', 'type': 'INNER',
            'leftTableId': 't1', 'leftColumn': 'id',
            'rightTableId': 't2', 'rightColumn': 'customer_id',
            'leftTable': 'customer', 'rightTable': 'order',
        }],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't2', 'columnName': 'total_amount'},
        ],
        'where': None,
        'having': None,
        'aggregations': [],
        'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100,
    }


def _explain_query(conn, qs):
    gen = SQLGenerator(qs)
    sql = gen.generate()
    params = gen.get_params()
    plan_sql = f'EXPLAIN QUERY PLAN {sql}'
    rows = conn.execute(text(plan_sql), params).fetchall()
    return [tuple(r) for r in rows]


# ---------------------------------------------------------------------------
# AST hash canonicality
# ---------------------------------------------------------------------------

class TestAstHashCanonicality:
    def test_identical_structure_same_hash(self):
        q1 = _base_query()
        q2 = copy.deepcopy(q1)
        assert compute_ast_hash(q1) == compute_ast_hash(q2)

    def test_ephemeral_node_ids_do_not_change_hash(self):
        q1 = _base_query()
        q2 = copy.deepcopy(q1)
        q2['tables'][0]['id'] = 'completely-different-id'
        q2['tables'][1]['id'] = 'another-id'
        q2['joins'][0]['id'] = 'different-join-id'
        q2['selectedFields'][0]['id'] = 'field-x'
        assert compute_ast_hash(q1) == compute_ast_hash(q2)

    def test_position_does_not_change_hash(self):
        q1 = _base_query()
        q2 = copy.deepcopy(q1)
        q2['tables'][0]['position'] = {'x': 100, 'y': 200}
        q2['tables'][1]['position'] = {'x': 999, 'y': 999}
        assert compute_ast_hash(q1) == compute_ast_hash(q2)

    def test_parameter_values_do_not_change_hash(self):
        q1 = _base_query()
        q1['where'] = {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country',
                 'cmp': '=', 'value': 'US'},
            ],
        }
        q2 = copy.deepcopy(q1)
        q2['where']['children'][0]['value'] = 'Germany'
        assert compute_ast_hash(q1) == compute_ast_hash(q2)

    def test_param_placeholder_name_changes_hash(self):
        q1 = _base_query()
        q1['where'] = {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country',
                 'cmp': '=', 'value': {'$param': 'country'}},
            ],
        }
        q2 = copy.deepcopy(q1)
        q2['where']['children'][0]['value'] = {'$param': 'nation'}
        assert compute_ast_hash(q1) != compute_ast_hash(q2)

    def test_join_type_change_changes_hash(self):
        q1 = _base_query()
        q2 = copy.deepcopy(q1)
        q2['joins'][0]['type'] = 'LEFT'
        assert compute_ast_hash(q1) != compute_ast_hash(q2)

    def test_filter_addition_changes_hash(self):
        q1 = _base_query()
        q2 = copy.deepcopy(q1)
        q2['where'] = {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country',
                 'cmp': '=', 'value': 'US'},
            ],
        }
        assert compute_ast_hash(q1) != compute_ast_hash(q2)

    def test_aggregation_change_changes_hash(self):
        q1 = _base_query()
        q2 = copy.deepcopy(q1)
        q2['aggregations'] = [
            {'tableId': 't2', 'columnName': 'total_amount',
             'function': 'SUM', 'alias': 'total'},
        ]
        assert compute_ast_hash(q1) != compute_ast_hash(q2)

    def test_whitespace_in_strings_irrelevant_to_hash(self):
        q1 = _base_query()
        q1['description'] = '  hello  '
        q2 = copy.deepcopy(q1)
        q2['description'] = 'hello'
        assert compute_ast_hash(q1) == compute_ast_hash(q2)

    def test_hash_deterministic_across_serialization(self):
        import json
        q = _base_query()
        h1 = compute_ast_hash(q)
        restored = json.loads(json.dumps(q))
        h2 = compute_ast_hash(restored)
        assert h1 == h2


# ---------------------------------------------------------------------------
# Parameter type summary (no values)
# ---------------------------------------------------------------------------

class TestParamTypeSummary:
    def test_records_types_only(self):
        params = [
            {'name': 'country', 'type': 'string', 'default': 'US'},
            {'name': 'page_size', 'type': 'integer', 'default': 10},
            {'name': 'window', 'type': 'date_range'},
        ]
        summary = compute_param_type_summary(params)
        assert summary == {
            'country': 'string',
            'page_size': 'integer',
            'window': 'date_range',
        }

    def test_does_not_leak_default_values(self):
        params = [{'name': 'secret', 'type': 'string', 'default': 'SENSITIVE_VALUE'}]
        summary = compute_param_type_summary(params)
        assert 'SENSITIVE_VALUE' not in str(summary)
        assert summary == {'secret': 'string'}

    def test_empty_params(self):
        assert compute_param_type_summary([]) == {}
        assert compute_param_type_summary(None) == {}


# ---------------------------------------------------------------------------
# Plan normalization
# ---------------------------------------------------------------------------

class TestPlanNormalization:
    def test_maps_table_aliases_to_ast_ids(self, db_connection):
        qs = _base_query()
        raw = _explain_query(db_connection, qs)
        ops = normalize_explain_plan(raw, qs)
        table_ops = [o for o in ops if o.get('tableId')]
        assert len(table_ops) >= 2
        table_ids = {o['tableId'] for o in table_ops}
        assert 't1' in table_ids
        assert 't2' in table_ids

    def test_maps_join_to_ast_join_id(self, db_connection):
        qs = _base_query()
        raw = _explain_query(db_connection, qs)
        ops = normalize_explain_plan(raw, qs)
        join_ops = [o for o in ops if o.get('joinId')]
        assert any(o['joinId'] == 'j1' for o in join_ops)

    def test_maps_filter_to_ast_node_key(self, db_connection):
        qs = _base_query()
        qs['where'] = {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country',
                 'cmp': '=', 'value': 'US'},
            ],
        }
        raw = _explain_query(db_connection, qs)
        ops = normalize_explain_plan(raw, qs)
        filter_keys = []
        for op in ops:
            for key in op.get('astNodeKeys', []):
                if key.startswith('filter:'):
                    filter_keys.append(key)
        assert any('t1' in k and 'country' in k for k in filter_keys)

    def test_maps_aggregation_to_ast_node_key(self, db_connection):
        qs = _base_query()
        qs['aggregations'] = [
            {'tableId': 't2', 'columnName': 'total_amount',
             'function': 'SUM', 'alias': 'total'},
        ]
        qs['selectedFields'] = [{'tableId': 't1', 'columnName': 'country'}]
        raw = _explain_query(db_connection, qs)
        ops = normalize_explain_plan(raw, qs)
        agg_keys = []
        for op in ops:
            for key in op.get('astNodeKeys', []):
                if key.startswith('agg:'):
                    agg_keys.append(key)
        assert any('SUM' in k and 'total_amount' in k for k in agg_keys)

    def test_no_sql_line_numbers_in_output(self, db_connection):
        qs = _base_query()
        raw = _explain_query(db_connection, qs)
        ops = normalize_explain_plan(raw, qs)
        serialized = str(ops)
        assert 'lineNumber' not in serialized
        assert 'line' not in serialized.lower().replace('online', '')


# ---------------------------------------------------------------------------
# Plan diff stability
# ---------------------------------------------------------------------------

class TestPlanDiffStability:
    def test_identical_queries_produce_empty_diff(self, db_connection):
        qs = _base_query()
        raw = _explain_query(db_connection, qs)
        ops1 = normalize_explain_plan(raw, qs)
        ops2 = normalize_explain_plan(copy.deepcopy(raw), copy.deepcopy(qs))
        diff = diff_plans(ops1, ops2)
        assert diff['summary']['hasChanges'] is False
        assert diff['summary']['added'] == 0
        assert diff['summary']['removed'] == 0
        assert diff['summary']['changed'] == 0

    def test_ephemeral_id_reassignment_produces_empty_diff(self, db_connection):
        """Same semantic query but with different AST node IDs → no diff."""
        qs1 = _base_query()
        raw1 = _explain_query(db_connection, qs1)
        ops1 = normalize_explain_plan(raw1, qs1)

        qs2 = copy.deepcopy(qs1)
        qs2['tables'][0]['id'] = 'different-id-1'
        qs2['tables'][1]['id'] = 'different-id-2'
        qs2['joins'][0]['id'] = 'different-join'
        qs2['joins'][0]['leftTableId'] = 'different-id-1'
        qs2['joins'][0]['rightTableId'] = 'different-id-2'
        for f in qs2['selectedFields']:
            f['tableId'] = 'different-id-1' if f['columnName'] in ('id', 'first_name') else 'different-id-2'
        qs2['orderBy'][0]['tableId'] = 'different-id-1'

        raw2 = _explain_query(db_connection, qs2)
        ops2 = normalize_explain_plan(raw2, qs2)

        diff = diff_plans(ops1, ops2)
        assert diff['summary']['hasChanges'] is False

    def test_join_type_change_produces_changeset(self, db_connection):
        qs1 = _base_query()
        qs2 = copy.deepcopy(_base_query())
        qs2['joins'][0]['type'] = 'LEFT'

        raw1 = _explain_query(db_connection, qs1)
        raw2 = _explain_query(db_connection, qs2)
        ops1 = normalize_explain_plan(raw1, qs1)
        ops2 = normalize_explain_plan(raw2, qs2)

        diff = diff_plans(ops1, ops2)
        assert diff['summary']['hasChanges'] is True

    def test_filter_addition_produces_ast_changes(self, db_connection):
        """Adding a WHERE clause on an unindexed column associates the filter
        with the table's AST node in the normalized plan operations.
        Also verify that removing ORDER BY (which removes the TEMP B-TREE)
        produces a real change set localized to the order_by AST node."""
        qs1 = _base_query()
        qs2 = copy.deepcopy(_base_query())
        qs2['where'] = {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't2', 'columnName': 'status',
                 'cmp': '=', 'value': 'pending'},
            ],
        }

        raw1 = _explain_query(db_connection, qs1)
        raw2 = _explain_query(db_connection, qs2)
        ops1 = normalize_explain_plan(raw1, qs1)
        ops2 = normalize_explain_plan(raw2, qs2)

        ops2_filter_keys = []
        for op in ops2:
            for key in op.get('astNodeKeys', []):
                if key.startswith('filter:'):
                    ops2_filter_keys.append(key)
        assert any('status' in k for k in ops2_filter_keys)

        qs3 = copy.deepcopy(_base_query())
        qs3['orderBy'] = []
        raw3 = _explain_query(db_connection, qs3)
        ops3 = normalize_explain_plan(raw3, qs3)
        diff_without_order = diff_plans(ops1, ops3)
        assert diff_without_order['summary']['hasChanges'] is True
        all_keys = set()
        for c in diff_without_order['astChanges']:
            all_keys.add(c['astNodeKey'])
        for op in diff_without_order['added'] + diff_without_order['removed']:
            all_keys.update(op.get('astNodeKeys', []))
        assert 'order_by' in all_keys

    def test_added_table_appears_in_added(self, db_connection):
        qs1 = _base_query()
        qs2 = copy.deepcopy(_base_query())
        qs2['tables'].append({
            'id': 't3', 'tableName': 'order_item', 'alias': 'oi',
        })
        qs2['joins'].append({
            'id': 'j2', 'type': 'INNER',
            'leftTableId': 't2', 'leftColumn': 'id',
            'rightTableId': 't3', 'rightColumn': 'order_id',
            'leftTable': 'order', 'rightTable': 'order_item',
        })
        qs2['selectedFields'].append({'tableId': 't3', 'columnName': 'quantity'})

        raw1 = _explain_query(db_connection, qs1)
        raw2 = _explain_query(db_connection, qs2)
        ops1 = normalize_explain_plan(raw1, qs1)
        ops2 = normalize_explain_plan(raw2, qs2)

        diff = diff_plans(ops1, ops2)
        added_tables = {o['tableId'] for o in diff['added'] if o.get('tableId')}
        assert 't3' in added_tables

    def test_removed_table_appears_in_removed(self, db_connection):
        qs1 = _base_query()
        qs2 = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [], 'limit': 100,
        }
        raw1 = _explain_query(db_connection, qs1)
        raw2 = _explain_query(db_connection, qs2)
        ops1 = normalize_explain_plan(raw1, qs1)
        ops2 = normalize_explain_plan(raw2, qs2)

        diff = diff_plans(ops1, ops2)
        removed_tables = {o['tableId'] for o in diff['removed'] if o.get('tableId')}
        assert 't2' in removed_tables

    def test_diff_symmetric_for_add_remove(self, db_connection):
        qs1 = _base_query()
        qs2 = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [], 'limit': 100,
        }
        raw1 = _explain_query(db_connection, qs1)
        raw2 = _explain_query(db_connection, qs2)
        ops1 = normalize_explain_plan(raw1, qs1)
        ops2 = normalize_explain_plan(raw2, qs2)

        forward = diff_plans(ops1, ops2)
        backward = diff_plans(ops2, ops1)

        assert forward['summary']['added'] == backward['summary']['removed']
        assert forward['summary']['removed'] == backward['summary']['added']

    def test_ast_changes_reference_join_ids(self, db_connection):
        qs1 = _base_query()
        qs2 = copy.deepcopy(_base_query())
        qs2['joins'][0]['type'] = 'LEFT'

        raw1 = _explain_query(db_connection, qs1)
        raw2 = _explain_query(db_connection, qs2)
        ops1 = normalize_explain_plan(raw1, qs1)
        ops2 = normalize_explain_plan(raw2, qs2)

        diff = diff_plans(ops1, ops2)
        all_ast_keys = set()
        for c in diff['astChanges']:
            all_ast_keys.add(c['astNodeKey'])
        for op in diff['added'] + diff['removed'] + [c.get('old') for c in diff['changed']] + [c.get('new') for c in diff['changed']]:
            if op:
                all_ast_keys.update(op.get('astNodeKeys', []))
        assert any(k == 'join:j1' for k in all_ast_keys)

    def test_fingerprint_ignores_node_and_parent_ids(self):
        op1 = {
            'nodeId': 2, 'parentId': 0,
            'tableId': 't1', 'operation': 'SCAN',
            'indexName': None, 'category': 'table_scan',
            'astNodeKeys': ['table:t1'],
        }
        op2 = {
            'nodeId': 99, 'parentId': 50,
            'tableId': 't1', 'operation': 'SCAN',
            'indexName': None, 'category': 'table_scan',
            'astNodeKeys': ['table:t1'],
        }
        assert _operation_fingerprint(op1) == _operation_fingerprint(op2)

    def test_fingerprint_detects_index_change(self):
        op1 = {
            'tableId': 't1', 'operation': 'SCAN',
            'indexName': None, 'category': 'table_scan',
            'astNodeKeys': ['table:t1'],
        }
        op2 = {
            'tableId': 't1', 'operation': 'SEARCH',
            'indexName': 'idx_country', 'category': 'index_access',
            'astNodeKeys': ['table:t1'],
        }
        assert _operation_fingerprint(op1) != _operation_fingerprint(op2)


# ---------------------------------------------------------------------------
# Snapshot creation and persistence
# ---------------------------------------------------------------------------

class TestSnapshotCreation:
    def test_create_snapshot_stores_metadata(self, db_connection):
        qs = _base_query()
        raw = _explain_query(db_connection, qs)
        snap = create_snapshot(
            query_structure=qs, raw_plan_rows=raw,
            row_count=10, duration_ms=2.5,
            parameters=[{'name': 'p', 'type': 'integer'}],
            template_id=1, template_version=3, label='v3',
        )
        assert snap['ast_hash']
        assert snap['row_count'] == 10
        assert snap['duration_ms'] == 2.5
        assert snap['template_id'] == 1
        assert snap['template_version'] == 3
        assert snap['label'] == 'v3'
        assert snap['param_type_summary'] == {'p': 'integer'}
        assert len(snap['plan_operations']) >= 2

    def test_snapshot_does_not_store_param_values(self, db_connection):
        qs = _base_query()
        raw = _explain_query(db_connection, qs)
        snap = create_snapshot(
            query_structure=qs, raw_plan_rows=raw,
            row_count=0, duration_ms=0,
            parameters=[{'name': 'secret', 'type': 'string', 'default': 'SENSITIVE'}],
        )
        serialized = str(snap)
        assert 'SENSITIVE' not in serialized


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

class TestPlanApi:
    def test_create_snapshot_via_api(self, client, db_connection):
        qs = _base_query()
        resp = client.post('/api/plan/snapshots', json={
            'query_structure': qs,
            'label': 'test snapshot',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['astHash']
        assert data['label'] == 'test snapshot'
        assert len(data['planOperations']) >= 2

    def test_list_snapshots(self, client):
        qs = _base_query()
        client.post('/api/plan/snapshots', json={
            'query_structure': qs, 'label': 'A',
        })
        client.post('/api/plan/snapshots', json={
            'query_structure': qs, 'label': 'B',
        })
        resp = client.get('/api/plan/snapshots')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 2

    def test_compare_snapshots_via_api(self, client, db_connection):
        qs1 = _base_query()
        s1 = client.post('/api/plan/snapshots', json={
            'query_structure': qs1,
        }).get_json()

        qs2 = copy.deepcopy(qs1)
        qs2['joins'][0]['type'] = 'LEFT'
        s2 = client.post('/api/plan/snapshots', json={
            'query_structure': qs2,
        }).get_json()

        resp = client.post('/api/plan/compare', json={
            'oldSnapshotId': s1['id'],
            'newSnapshotId': s2['id'],
        })
        assert resp.status_code == 200
        diff = resp.get_json()
        assert diff['summary']['hasChanges'] is True

    def test_compare_structures_via_api(self, client):
        qs1 = _base_query()
        qs2 = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [], 'limit': 100,
        }
        resp = client.post('/api/plan/compare', json={
            'oldStructure': qs1,
            'newStructure': qs2,
        })
        assert resp.status_code == 200
        diff = resp.get_json()
        assert diff['summary']['hasChanges'] is True

    def test_compare_identical_structures_empty_diff(self, client):
        qs = _base_query()
        resp = client.post('/api/plan/compare', json={
            'oldStructure': qs,
            'newStructure': copy.deepcopy(qs),
        })
        assert resp.status_code == 200
        diff = resp.get_json()
        assert diff['summary']['hasChanges'] is False

    def test_snapshot_persists_to_db(self, app, client):
        with app.app_context():
            qs = _base_query()
            client.post('/api/plan/snapshots', json={
                'query_structure': qs, 'label': 'persist-test',
            })
            count = PlanSnapshot.query.count()
            assert count >= 1
            snap = PlanSnapshot.query.filter_by(label='persist-test').first()
            assert snap is not None
            assert snap.ast_hash
            assert snap.param_type_summary == {}
            assert isinstance(snap.normalized_plan, list)

    def test_template_execute_captures_snapshot(self, client, app):
        from app.services.template_service import TemplateService
        from app.models import QueryTemplate
        qs = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'country'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country',
                     'cmp': '=', 'value': {'$param': 'country'}},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 10,
        }
        params = [{'name': 'country', 'type': 'string', 'required': True}]
        built = TemplateService.build_template('Snap', qs, params)
        with app.app_context():
            tpl = QueryTemplate(**{k: built[k] for k in
                ('name', 'description', 'version', 'query_structure',
                 'parameters', 'schema_refs')})
            _db.session.add(tpl)
            _db.session.commit()
            tpl_id = tpl.id

        resp = client.post(f'/api/templates/{tpl_id}/execute', json={
            'parameters': {'country': 'US'},
            'captureSnapshot': True,
            'label': 'execution-snap',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'snapshot' in data
        assert data['snapshot']['templateId'] == tpl_id
        assert data['snapshot']['label'] == 'execution-snap'
        assert data['snapshot']['paramTypeSummary'] == {'country': 'string'}
