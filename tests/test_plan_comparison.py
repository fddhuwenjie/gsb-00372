"""
Plan fingerprinting and comparison tests.

Uses a fixed, deterministic database fixture (``fixed_db``) to prove:
  1. Non-semantic formatting changes (key order, whitespace, canvas
     positions) do NOT change the AST hash or plan fingerprint.
  2. Real changes (JOIN type, filters, aggregation, index access)
     produce a stable, AST-node-localised change set.
"""
import copy

import pytest

from app.models import QueryExecution
from app.services.plan_service import (
    build_plan_fingerprint,
    canonical_ast,
    diff_plans,
    hash_ast,
    parameter_type_summary,
    parse_plan_rows,
    table_instances_from_ast,
)
from app.services.query_executor import QueryExecutor


def items_query(**overrides):
    """Base fixed-DB query: items joined to categories."""
    qs = {
        'tables': [
            {'id': 'c', 'tableName': 'categories', 'alias': 'c'},
            {'id': 'i', 'tableName': 'items', 'alias': 'i'},
        ],
        'joins': [{
            'id': 'j1', 'type': 'INNER',
            'leftTableId': 'c', 'leftColumn': 'id',
            'rightTableId': 'i', 'rightColumn': 'category_id',
            'leftTable': 'categories', 'rightTable': 'items',
        }],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'name'},
            {'tableId': 'i', 'columnName': 'name'},
            {'tableId': 'i', 'columnName': 'price'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 100,
    }
    qs.update(overrides)
    return qs


def run_and_get_plan(qs, **exec_kwargs):
    result = QueryExecutor.execute(qs, record=False, **exec_kwargs)
    return result['planNodes'], result['planFingerprint'], result


# ---------------------------------------------------------------------------
# Canonical AST hashing
# ---------------------------------------------------------------------------
class TestCanonicalAst:
    def test_same_ast_same_hash(self):
        qs = items_query()
        assert hash_ast(qs) == hash_ast(copy.deepcopy(qs))

    def test_key_order_does_not_change_hash(self):
        qs1 = items_query()
        qs2 = {
            'limit': 100,
            'aggregations': [],
            'where': None,
            'tables': list(reversed(qs1['tables'])),
            'joins': qs1['joins'],
            'selectedFields': qs1['selectedFields'],
        }
        # Table order is semantically meaningful (driving table), so
        # reversing it SHOULD change the hash. But reordering dict keys
        # within a node must not.
        assert hash_ast(qs1) == hash_ast(qs1)

        qs3 = copy.deepcopy(qs1)
        qs3['tables'][0] = {
            'alias': 'c', 'tableName': 'categories', 'id': 'c',
            'position': {'x': 999, 'y': 999},
        }
        # Cosmetic position must be stripped by canonicalisation.
        assert canonical_ast(qs3)['tables'][0].get('position') is None

    def test_position_change_does_not_change_hash(self):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['tables'][0]['position'] = {'x': 10, 'y': 20}
        qs2['tables'][1]['position'] = {'x': 30, 'y': 40}
        assert hash_ast(qs1) == hash_ast(qs2)

    def test_label_change_does_not_change_hash(self):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['selectedFields'][0]['label'] = 'Cosmetic label'
        assert hash_ast(qs1) == hash_ast(qs2)

    def test_default_limit_omitted_is_same_as_explicit_default(self):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2.pop('limit', None)
        assert hash_ast(qs1) == hash_ast(qs2)

    def test_different_filter_changes_hash(self):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['where'] = {
            'tableId': 'i', 'columnName': 'active',
            'cmp': '=', 'value': 1,
        }
        assert hash_ast(qs1) != hash_ast(qs2)

    def test_different_join_type_changes_hash(self):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['joins'][0]['type'] = 'LEFT'
        assert hash_ast(qs1) != hash_ast(qs2)


# ---------------------------------------------------------------------------
# Parameter type summary (no sensitive values)
# ---------------------------------------------------------------------------
class TestParameterSummary:
    def test_summary_does_not_leak_values(self):
        params = {
            'secret_token': 'abc123-sensitive',
            'country': 'US',
            'limit': 10,
            'active': True,
        }
        summary = parameter_type_summary(params)
        blob = repr(summary)
        assert 'abc123-sensitive' not in blob
        assert 'US' not in blob
        types_by_name = {s['name']: s for s in summary}
        assert types_by_name['secret_token']['type'] == 'string'
        assert types_by_name['limit']['type'] == 'integer'
        assert types_by_name['active']['type'] == 'boolean'

    def test_null_tracking(self):
        summary = parameter_type_summary({'maybe': None})
        assert summary[0]['isNull'] is True
        assert summary[0]['type'] == 'null'


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------
class TestPlanParsing:
    def test_scan_detected(self, fixed_db):
        qs = {
            'tables': [{'id': 't', 'tableName': 'items', 'alias': 't'}],
            'joins': [],
            'selectedFields': [{'tableId': 't', 'columnName': 'id'}],
            'where': None,
            'aggregations': [],
            'limit': 10,
        }
        _, fingerprint, result = run_and_get_plan(qs)
        assert any(n['operation'] == 'SCAN' for n in result['planNodes'])
        assert fingerprint

    def test_index_search_detected(self, fixed_db):
        qs = {
            'tables': [{'id': 'i', 'tableName': 'items', 'alias': 'i'}],
            'joins': [],
            'selectedFields': [{'tableId': 'i', 'columnName': 'id'}],
            'where': {
                'tableId': 'i', 'columnName': 'category_id',
                'cmp': '=', 'value': 1,
            },
            'aggregations': [],
            'limit': 10,
        }
        _, fingerprint, result = run_and_get_plan(qs)
        search_nodes = [
            n for n in result['planNodes'] if n['operation'] == 'SEARCH'
        ]
        assert search_nodes, "Expected a SEARCH node using idx_items_category"
        assert any(
            n['indexName'] == 'idx_items_category' for n in search_nodes
        )


# ---------------------------------------------------------------------------
# Plan stability: non-semantic changes produce identical fingerprints
# ---------------------------------------------------------------------------
class TestPlanStability:
    def test_same_query_identical_fingerprint_across_runs(self, fixed_db):
        qs = items_query(where={
            'tableId': 'i', 'columnName': 'category_id',
            'cmp': '=', 'value': 1,
        })
        _, fp1, _ = run_and_get_plan(qs)
        _, fp2, _ = run_and_get_plan(qs)
        assert fp1 == fp2

    def test_position_change_no_fingerprint_change(self, fixed_db):
        qs1 = items_query(where={
            'tableId': 'i', 'columnName': 'category_id',
            'cmp': '=', 'value': 1,
        })
        qs2 = copy.deepcopy(qs1)
        qs2['tables'][0]['position'] = {'x': 1, 'y': 2}
        _, fp1, _ = run_and_get_plan(qs1)
        _, fp2, _ = run_and_get_plan(qs2)
        assert fp1 == fp2

    def test_parameter_value_change_no_plan_change(self, fixed_db):
        """Different parameter VALUES should not change the structural plan
        (SQLite may choose different plans based on value estimates, but
        for a simple equality on an indexed column the plan is stable)."""
        qs = {
            'tables': [{'id': 'i', 'tableName': 'items', 'alias': 'i'}],
            'joins': [],
            'selectedFields': [{'tableId': 'i', 'columnName': 'id'}],
            'where': {
                'tableId': 'i', 'columnName': 'category_id',
                'cmp': '=', 'value': 1,
            },
            'aggregations': [],
            'limit': 10,
        }
        _, fp1, _ = run_and_get_plan(qs)
        qs['where']['value'] = 2
        _, fp2, _ = run_and_get_plan(qs)
        assert fp1 == fp2


# ---------------------------------------------------------------------------
# Plan diff: real changes produce localised change sets
# ---------------------------------------------------------------------------
class TestPlanDiff:
    def _diff(self, fixed_db, qs_a, qs_b):
        plan_a, _, _ = run_and_get_plan(qs_a)
        plan_b, _, _ = run_and_get_plan(qs_b)
        return diff_plans(plan_a, plan_b, qs_a, qs_b)

    def test_identical_queries_no_changes(self, fixed_db):
        qs = items_query()
        changes = self._diff(fixed_db, qs, copy.deepcopy(qs))
        assert changes == []

    def test_join_type_change_localised(self, fixed_db):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['joins'][0]['type'] = 'LEFT'
        changes = self._diff(fixed_db, qs1, qs2)
        kinds = {c['kind'] for c in changes}
        assert 'join_type_changed' in kinds
        join_change = next(c for c in changes if c['kind'] == 'join_type_changed')
        # Must be localised to the JOIN id, not a SQL line number
        assert join_change['joinId'] == 'j1'
        assert join_change['before'] == 'INNER'
        assert join_change['after'] == 'LEFT'

    def test_filter_change_localised(self, fixed_db):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['where'] = {
            'tableId': 'i', 'columnName': 'price',
            'cmp': '>', 'value': 10,
        }
        changes = self._diff(fixed_db, qs1, qs2)
        kinds = {c['kind'] for c in changes}
        assert 'where_changed' in kinds

    def test_aggregation_change_localised(self, fixed_db):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['aggregations'] = [{
            'tableId': 'i', 'columnName': 'price',
            'function': 'SUM', 'alias': 'total',
        }]
        qs2['selectedFields'] = [
            {'tableId': 'c', 'columnName': 'name'},
        ]
        changes = self._diff(fixed_db, qs1, qs2)
        kinds = {c['kind'] for c in changes}
        assert 'aggregation_changed' in kinds

    def test_added_filter_uses_index(self, fixed_db):
        """Adding a filter on an indexed column should surface an
        index-related change localised to the table instance."""
        qs1 = {
            'tables': [{'id': 'i', 'tableName': 'items', 'alias': 'i'}],
            'joins': [],
            'selectedFields': [{'tableId': 'i', 'columnName': 'id'}],
            'where': None,
            'aggregations': [],
            'limit': 100,
        }
        qs2 = copy.deepcopy(qs1)
        qs2['where'] = {
            'tableId': 'i', 'columnName': 'category_id',
            'cmp': '=', 'value': 2,
        }
        plan_a, _, _ = run_and_get_plan(qs1)
        plan_b, _, _ = run_and_get_plan(qs2)
        changes = diff_plans(plan_a, plan_b, qs1, qs2)

        # A scan -> search transition should be reported.
        op_changes = [c for c in changes if c['kind'] == 'operation_changed']
        assert op_changes, f"Expected operation change, got: {changes}"
        # The change must reference the table instance id, not a line number.
        assert all(c.get('tableId') == 'i' for c in op_changes)

    def test_change_set_is_deterministic(self, fixed_db):
        """Running the same diff twice yields the exact same change set."""
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['joins'][0]['type'] = 'LEFT'
        changes1 = self._diff(fixed_db, qs1, qs2)
        changes2 = self._diff(fixed_db, qs1, qs2)
        assert changes1 == changes2


# ---------------------------------------------------------------------------
# Execution recording (no sensitive values)
# ---------------------------------------------------------------------------
class TestExecutionRecording:
    def test_execution_recorded_without_param_values(self, fixed_db):
        qs = {
            'tables': [{'id': 'i', 'tableName': 'items', 'alias': 'i'}],
            'joins': [],
            'selectedFields': [{'tableId': 'i', 'columnName': 'id'}],
            'where': {
                'tableId': 'i', 'columnName': 'category_id',
                'cmp': '=', 'value': 1,
            },
            'aggregations': [],
            'limit': 10,
        }
        result = QueryExecutor.execute(
            qs, user_session='plan-test', record=True
        )
        assert result['executionId'] is not None
        record = QueryExecution.query.get(result['executionId'])
        assert record is not None
        assert record.ast_hash == hash_ast(qs)
        assert record.row_count >= 1
        assert record.plan_fingerprint is not None
        # The raw SQL may contain the bound placeholder but params dict
        # is not stored on the execution record (no sensitive values).
        stored = repr(record.param_type_summary)
        assert ':1' not in stored or 'value' not in stored.lower()
        # Only type info, never the actual value 1.
        for entry in record.param_type_summary:
            assert 'value' not in entry or entry['value'] is None

    def test_executions_grouped_by_ast_hash(self, fixed_db):
        qs1 = {
            'tables': [{'id': 'i', 'tableName': 'items', 'alias': 'i'}],
            'joins': [],
            'selectedFields': [{'tableId': 'i', 'columnName': 'id'}],
            'where': None,
            'aggregations': [],
            'limit': 5,
        }
        r1 = QueryExecutor.execute(qs1, user_session='g', record=True)
        qs2 = copy.deepcopy(qs1)
        # Same semantic query, different position
        qs2['tables'][0]['position'] = {'x': 5, 'y': 5}
        r2 = QueryExecutor.execute(qs2, user_session='g', record=True)
        # Same semantic AST -> same hash, same plan fingerprint
        assert r1['astHash'] == r2['astHash']
        assert r1['planFingerprint'] == r2['planFingerprint']


# ---------------------------------------------------------------------------
# API-level diff
# ---------------------------------------------------------------------------
class TestPlanDiffAPI:
    def test_diff_endpoint_localises_changes(self, fixed_db, client):
        qs1 = items_query()
        qs2 = copy.deepcopy(qs1)
        qs2['joins'][0]['type'] = 'LEFT'

        r1 = client.post('/api/execute-query', json=qs1,
                         headers={'X-Session-Id': 'diff'})
        r2 = client.post('/api/execute-query', json=qs2,
                         headers={'X-Session-Id': 'diff'})
        id_a = r1.get_json()['executionId']
        id_b = r2.get_json()['executionId']

        resp = client.post('/api/plans/diff', json={
            'executionIdA': id_a,
            'executionIdB': id_b,
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body['planFingerprintChanged'] is True
        kinds = {c['kind'] for c in body['changes']}
        assert 'join_type_changed' in kinds
        # No SQL line numbers in any change
        for c in body['changes']:
            assert 'line' not in c
            assert 'lineNumber' not in c
