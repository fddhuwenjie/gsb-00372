"""Front/back AST round-trip tests.

The unified AST is the single contract the React store serializes and the
backend consumes. These tests assert that the semantics of a query are
invariant under the transformations the UI performs: JSON save/reopen,
JOIN reordering, table reordering, and share restore. Because field
references are bound to stable table-instance ids, none of these change the
generated SQL's meaning -- proven by comparing executed results.
"""
import json
import copy
from app.services.query_executor import QueryExecutor
from app.services.sql_generator import SQLGenerator


def _rows(app, qs):
    with app.app_context():
        return QueryExecutor.execute(qs, max_rows=1000)['rows']


def three_table_ast():
    return {
        'tables': [
            {'id': 'inst-c', 'tableName': 'customer', 'alias': 'c', 'position': {'x': 0, 'y': 0}},
            {'id': 'inst-o', 'tableName': 'order', 'alias': 'o', 'position': {'x': 1, 'y': 0}},
            {'id': 'inst-e', 'tableName': 'employee', 'alias': 'e', 'position': {'x': 2, 'y': 0}},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
             'rightTableId': 'inst-c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'},
            {'id': 'j2', 'type': 'LEFT', 'leftTableId': 'o', 'leftColumn': 'employee_id',
             'rightTableId': 'inst-e', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'employee'},
        ],
        'selectedFields': [{'tableId': 'inst-c', 'columnName': 'first_name'},
                           {'tableId': 'inst-e', 'columnName': 'first_name'},
                           {'tableId': 'inst-o', 'columnName': 'id'}],
        'where': None, 'aggregations': [],
        'orderBy': [{'tableId': 'inst-o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100,
    }


def _fix_ids(ast):
    # The fixture uses 'o' as a join id shorthand; normalize to 'inst-o'.
    for j in ast['joins']:
        if j['leftTableId'] == 'o':
            j['leftTableId'] = 'inst-o'
        if j['rightTableId'] == 'o':
            j['rightTableId'] = 'inst-o'
    return ast


def test_roundtrip_json_save_reopen(app):
    ast = _fix_ids(three_table_ast())
    reopened = json.loads(json.dumps(ast))
    assert _rows(app, ast) == _rows(app, reopened)


def test_roundtrip_join_reorder(app):
    ast = _fix_ids(three_table_ast())
    reordered = copy.deepcopy(ast)
    reordered['joins'] = list(reversed(reordered['joins']))
    # Reordering the JOIN array must not change results (ids bind fields).
    assert _rows(app, ast) == _rows(app, reordered)


def test_roundtrip_table_reorder_stable_sql(app):
    ast = _fix_ids(three_table_ast())
    reordered = copy.deepcopy(ast)
    reordered['tables'] = [reordered['tables'][2], reordered['tables'][0], reordered['tables'][1]]
    assert _rows(app, ast) == _rows(app, reordered)


def test_roundtrip_share_restore(app):
    # Share restore reconstructs the AST from stored JSON; results identical.
    ast = _fix_ids(three_table_ast())
    stored = json.dumps({'query_structure': ast})
    restored = json.loads(stored)['query_structure']
    assert _rows(app, ast) == _rows(app, restored)


def test_field_reference_bound_to_instance_not_name(app):
    # Duplicate table (self-join): identically-named columns must resolve to
    # the correct instance via id, producing two distinct qualified columns.
    ast = {
        'tables': [
            {'id': 'a', 'tableName': 'order', 'alias': 'o1', 'position': {}},
            {'id': 'b', 'tableName': 'order', 'alias': 'o2', 'position': {}},
        ],
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'a', 'leftColumn': 'customer_id',
                   'rightTableId': 'b', 'rightColumn': 'customer_id', 'leftTable': 'order', 'rightTable': 'order'}],
        'selectedFields': [{'tableId': 'a', 'columnName': 'id'}, {'tableId': 'b', 'columnName': 'id'}],
        'where': None, 'aggregations': [], 'limit': 10,
    }
    sql = SQLGenerator(ast).generate()
    assert '"o1"."id"' in sql and '"o2"."id"' in sql
