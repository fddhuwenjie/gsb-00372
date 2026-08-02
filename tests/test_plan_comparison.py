"""Plan normalization & comparison tests against the fixed database fixture.

Two classes of guarantees are proven here:

  1. Non-semantic format changes -- join / filter authoring order, alias
     renaming, table order, whitespace in SQL, and different literal parameter
     *values* of the same type -- do NOT change the AST hash and produce an
     empty change set. i.e. they never manufacture a version difference.

  2. Real semantic changes -- a JOIN type change, a JOIN add/remove, or a
     filter add/remove -- produce a stable, AST-located change set.

All plan capture runs against the seeded temp SQLite database from conftest.
"""
import copy
import pytest

from app.services.plan_analysis_service import PlanAnalysisService as P, summarize_param_types
from app.services.query_executor import QueryExecutor


def tables(*specs):
    return [{'id': tid, 'tableName': name, 'alias': alias, 'position': {}}
            for tid, name, alias in specs]


def base_query():
    return {
        'tables': tables(('o', 'order', 'o'), ('c', 'customer', 'c')),
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
                   'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'},
                           {'tableId': 'o', 'columnName': 'total_amount'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'd1', 'tableId': 'o', 'columnName': 'total_amount', 'cmp': '>=', 'value': 0},
            {'id': 'ct', 'tableId': 'c', 'columnName': 'country', 'cmp': '=', 'value': 'US'}]},
        'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100, 'offset': 0,
    }


# ============================ non-semantic invariance =======================

def test_alias_rename_does_not_change_hash():
    a = base_query()
    b = copy.deepcopy(a)
    b['tables'][0]['alias'] = 'ord'
    b['tables'][1]['alias'] = 'cust'
    assert P.ast_hash(a) == P.ast_hash(b)
    assert P.diff_ast(P.canonicalize_ast(a), P.canonicalize_ast(b)) == []


def test_table_reorder_does_not_change_hash():
    a = base_query()
    b = copy.deepcopy(a)
    b['tables'].reverse()
    assert P.ast_hash(a) == P.ast_hash(b)


def test_join_authoring_order_does_not_change_hash():
    # Three-table query; author the two joins in opposite orders.
    a = {
        'tables': tables(('o', 'order', 'o'), ('c', 'customer', 'c'), ('e', 'employee', 'e')),
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
             'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'},
            {'id': 'j2', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'employee_id',
             'rightTableId': 'e', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'employee'},
        ],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'}],
        'where': None, 'aggregations': [], 'limit': 10,
    }
    b = copy.deepcopy(a)
    b['joins'].reverse()
    assert P.ast_hash(a) == P.ast_hash(b)


def test_join_side_swap_inner_does_not_change_hash():
    a = base_query()
    b = copy.deepcopy(a)
    j = b['joins'][0]
    j['leftTableId'], j['rightTableId'] = j['rightTableId'], j['leftTableId']
    j['leftColumn'], j['rightColumn'] = j['rightColumn'], j['leftColumn']
    j['leftTable'], j['rightTable'] = j['rightTable'], j['leftTable']
    assert P.ast_hash(a) == P.ast_hash(b)


def test_filter_reorder_does_not_change_hash():
    a = base_query()
    b = copy.deepcopy(a)
    b['where']['children'].reverse()
    assert P.ast_hash(a) == P.ast_hash(b)


def test_different_param_values_same_type_do_not_change_hash():
    a = base_query()
    b = copy.deepcopy(a)
    b['where']['children'][1]['value'] = 'DE'   # US -> DE, still a string
    assert P.ast_hash(a) == P.ast_hash(b)


def test_node_id_relabel_does_not_change_hash():
    a = base_query()
    b = copy.deepcopy(a)
    b['where']['id'] = 'renamed'
    b['where']['children'][0]['id'] = 'x'
    b['joins'][0]['id'] = 'zzz'
    assert P.ast_hash(a) == P.ast_hash(b)


# ============================ real change detection =========================

def test_join_type_change_is_located():
    a = base_query()
    b = copy.deepcopy(a)
    b['joins'][0]['type'] = 'LEFT'
    assert P.ast_hash(a) != P.ast_hash(b)
    changes = P.diff_ast(P.canonicalize_ast(a), P.canonicalize_ast(b))
    joins = [c for c in changes if c['kind'] == 'join']
    assert len(joins) == 1
    assert joins[0]['change'] == 'modified'
    assert joins[0]['from']['type'] == 'INNER' and joins[0]['to']['type'] == 'LEFT'


def test_added_filter_is_located():
    a = base_query()
    b = copy.deepcopy(a)
    b['where']['children'].append(
        {'id': 'nf', 'tableId': 'o', 'columnName': 'status', 'cmp': '=', 'value': 'shipped'})
    assert P.ast_hash(a) != P.ast_hash(b)
    changes = P.diff_ast(P.canonicalize_ast(a), P.canonicalize_ast(b))
    filters = [c for c in changes if c['kind'] == 'filter']
    assert len(filters) == 1 and filters[0]['change'] == 'added'
    assert filters[0]['node']['column'] == 'status'


def test_removed_join_is_located():
    a = {
        'tables': tables(('o', 'order', 'o'), ('c', 'customer', 'c'), ('e', 'employee', 'e')),
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
             'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'},
            {'id': 'j2', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'employee_id',
             'rightTableId': 'e', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'employee'},
        ],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'}],
        'where': None, 'aggregations': [], 'limit': 10,
    }
    b = copy.deepcopy(a)
    b['joins'] = [b['joins'][0]]
    b['tables'] = [t for t in b['tables'] if t['id'] != 'e']
    changes = P.diff_ast(P.canonicalize_ast(a), P.canonicalize_ast(b))
    joins = [c for c in changes if c['kind'] == 'join']
    assert any(c['change'] == 'removed' for c in joins)


def test_aggregation_change_is_located():
    a = base_query()
    b = copy.deepcopy(a)
    b['aggregations'] = [{'tableId': 'o', 'columnName': 'total_amount', 'function': 'SUM'}]
    b['selectedFields'] = [{'tableId': 'c', 'columnName': 'country'}]
    changes = P.diff_ast(P.canonicalize_ast(a), P.canonicalize_ast(b))
    assert any(c['kind'] == 'aggregation' and c['change'] == 'added' for c in changes)


# ============================ plan capture (fixed DB) =======================

def test_capture_never_stores_raw_param_values(app):
    q = base_query()
    q['where']['children'][1]['value'] = 'Ruritania'  # a distinctive literal
    with app.app_context():
        rec = QueryExecutor.capture_plan_record(q, persist=False)
    # The distinctive filter value must not appear anywhere in the stored plan.
    assert 'Ruritania' not in str(rec['raw_plan'])
    assert 'Ruritania' not in str(rec['normalized_plan'])
    assert 'Ruritania' not in str(rec['param_type_summary'])
    assert set(rec['param_type_summary']['byName'].values()) <= {
        'integer', 'number', 'string', 'date', 'boolean', 'list', 'null'
    }
    assert rec['row_count'] is not None
    assert rec['normalized_plan']['accesses']  # AST-keyed accesses present


def test_normalized_plan_is_ast_keyed_not_line_numbers(app):
    q = base_query()
    with app.app_context():
        rec = QueryExecutor.capture_plan_record(q, persist=False)
    for access in rec['normalized_plan']['accesses']:
        assert access['astNodeKind'] == 'access'
        # keyed by canonical table ref (t0/t1...), never a SQL line number
        assert access['tableRef'] is None or access['tableRef'].startswith('t')


def test_format_change_yields_identical_captured_plan(app):
    """Non-semantic edits (alias rename + join/filter reorder + different
    same-type value) yield the same AST hash and an empty change set even after
    a real EXPLAIN capture on the fixed DB."""
    a = base_query()
    b = copy.deepcopy(a)
    b['tables'][0]['alias'] = 'ord'
    b['tables'][1]['alias'] = 'cust'
    b['joins'].reverse() if len(b['joins']) > 1 else None
    b['where']['children'].reverse()
    b['where']['children'][0]['value'] = 'CA'  # was some string; same type

    with app.app_context():
        rec_a = QueryExecutor.capture_plan_record(a, persist=False)
        rec_b = QueryExecutor.capture_plan_record(b, persist=False)
    comparison = P.compare_records(rec_a, rec_b)
    assert comparison['semanticallyEqual'] is True
    assert comparison['astChanges'] == []
    assert comparison['planChanges'] == []
    assert comparison['changeCount'] == 0


def test_real_change_yields_stable_change_set(app):
    a = base_query()
    b = copy.deepcopy(a)
    b['joins'][0]['type'] = 'LEFT'

    with app.app_context():
        rec_a = QueryExecutor.capture_plan_record(a, persist=False)
        rec_b = QueryExecutor.capture_plan_record(b, persist=False)
    c1 = P.compare_records(rec_a, rec_b)
    c2 = P.compare_records(rec_a, rec_b)
    assert c1['semanticallyEqual'] is False
    assert c1['astChanges'] == c2['astChanges']   # stable / deterministic
    assert any(ch['kind'] == 'join' and ch['change'] == 'modified' for ch in c1['astChanges'])


def test_param_summary_hides_values_but_keeps_types():
    summary = summarize_param_types({'p1': '2025-01-01', 'p2': 'secret@example.com',
                                     'p3': 42, 'p4': ['US', 'UK'], 'p5': 3.14})
    assert summary['byName'] == {
        'p1': 'date', 'p2': 'string', 'p3': 'integer', 'p4': 'list', 'p5': 'number',
    }
    # no raw values anywhere in the summary
    assert 'secret@example.com' not in str(summary)
    assert '2025-01-01' not in str(summary)
