"""
API differential tests.

Every visually constructed query is executed both via the API (which compiles
the AST) and via an equivalent, hand-written, parameterised SQL statement
against the *same* temporary SQLite database. The result sets must match.

These tests use Flask's test client -- no running server and no fixed
sakila.db are required.
"""
from datetime import date

import pytest
from sqlalchemy import text

from app.database import db
from app.services.query_executor import QueryExecutor


def run_handwritten(sql, params=None):
    result = db.session.execute(text(sql), params or {})
    return [list(row) for row in result.fetchall()]


def run_ast(qs):
    return QueryExecutor.execute(qs)


def assert_same_rows(ast_rows, hand_rows, labels=('ast', 'hand')):
    ast_set = {tuple(r) for r in ast_rows}
    hand_set = {tuple(r) for r in hand_rows}
    assert ast_set == hand_set, (
        f'Result mismatch:\n'
        f'  only in {labels[0]}: {list(ast_set - hand_set)[:5]}\n'
        f'  only in {labels[1]}: {list(hand_set - ast_set)[:5]}'
    )


# ---------------------------------------------------------------------------
# 1. Basic INNER JOIN differential
# ---------------------------------------------------------------------------
def test_inner_join_differential(app_context):
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
            {'tableId': 'c', 'columnName': 'first_name'},
            {'tableId': 'c', 'columnName': 'country'},
            {'tableId': 'o', 'columnName': 'total_amount'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.first_name, c.country, o.total_amount '
        'FROM customer c INNER JOIN "order" o ON c.id = o.customer_id '
        'LIMIT :lim',
        {'lim': 100},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 2. Nested AND/OR WHERE
# ---------------------------------------------------------------------------
def test_nested_where_differential(app_context):
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
            {'tableId': 'c', 'columnName': 'first_name'},
            {'tableId': 'c', 'columnName': 'country'},
            {'tableId': 'o', 'columnName': 'total_amount'},
        ],
        'where': {
            'op': 'AND',
            'children': [
                {'tableId': 'o', 'columnName': 'total_amount',
                 'cmp': '>', 'value': 100},
                {'op': 'OR', 'children': [
                    {'tableId': 'c', 'columnName': 'country',
                     'cmp': '=', 'value': 'US'},
                    {'tableId': 'c', 'columnName': 'country',
                     'cmp': '=', 'value': 'UK'},
                ]},
            ],
        },
        'aggregations': [],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.first_name, c.country, o.total_amount '
        'FROM customer c INNER JOIN "order" o ON c.id = o.customer_id '
        'WHERE (o.total_amount > :amt AND (c.country = :u OR c.country = :k)) '
        'LIMIT :lim',
        {'amt': 100, 'u': 'US', 'k': 'UK', 'lim': 100},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 3. NOT condition
# ---------------------------------------------------------------------------
def test_not_condition_differential(app_context):
    qs = {
        'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'id'},
            {'tableId': 'c', 'columnName': 'country'},
        ],
        'where': {
            'op': 'NOT',
            'child': {'tableId': 'c', 'columnName': 'country',
                      'cmp': '=', 'value': 'US'},
        },
        'aggregations': [],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.id, c.country FROM customer c '
        'WHERE NOT (c.country = :u) LIMIT :lim',
        {'u': 'US', 'lim': 100},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 4. Aggregation + GROUP BY + HAVING
# ---------------------------------------------------------------------------
def test_aggregation_having_differential(app_context):
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
            {'tableId': 'o', 'columnName': 'total_amount', 'function': 'SUM',
             'alias': 'total_spent'},
        ],
        'having': {
            'tableId': 'o', 'columnName': 'total_amount',
            'cmp': '>', 'value': 500, 'function': 'SUM',
        },
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.country, SUM(o.total_amount) AS total_spent '
        'FROM customer c INNER JOIN "order" o ON c.id = o.customer_id '
        'GROUP BY c.country '
        'HAVING SUM(o.total_amount) > :h '
        'LIMIT :lim',
        {'h': 500, 'lim': 100},
    )
    # Compare as dicts to avoid column order issues
    ast_d = {r[0]: round(float(r[1]), 2) for r in ast['rows']}
    hand_d = {r[0]: round(float(r[1]), 2) for r in hand}
    assert ast_d == hand_d


# ---------------------------------------------------------------------------
# 5. LEFT JOIN
# ---------------------------------------------------------------------------
def test_left_join_differential(app_context):
    qs = {
        'tables': [
            {'id': 'c', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'o', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [{
            'id': 'j', 'type': 'LEFT',
            'leftTableId': 'c', 'leftColumn': 'id',
            'rightTableId': 'o', 'rightColumn': 'customer_id',
            'leftTable': 'customer', 'rightTable': 'order',
        }],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'id'},
            {'tableId': 'o', 'columnName': 'id'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 1000,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.id, o.id FROM customer c '
        'LEFT JOIN "order" o ON c.id = o.customer_id LIMIT :lim',
        {'lim': 1000},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 6. Self-join (employee reporting structure is not seeded, but we join the
#    table to itself to exercise alias disambiguation)
# ---------------------------------------------------------------------------
def test_self_join_differential(app_context):
    qs = {
        'tables': [
            {'id': 'e1', 'tableName': 'employee', 'alias': 'e1'},
            {'id': 'e2', 'tableName': 'employee', 'alias': 'e2'},
        ],
        'joins': [{
            'id': 'j', 'type': 'INNER',
            'leftTableId': 'e1', 'leftColumn': 'department',
            'rightTableId': 'e2', 'rightColumn': 'department',
            'leftTable': 'employee', 'rightTable': 'employee',
        }],
        'selectedFields': [
            {'tableId': 'e1', 'columnName': 'id'},
            {'tableId': 'e2', 'columnName': 'id'},
        ],
        'where': {
            'tableId': 'e1', 'columnName': 'id', 'cmp': '<',
            'value': 99999,
        },
        'aggregations': [],
        'limit': 1000,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT e1.id, e2.id FROM employee e1 '
        'INNER JOIN employee e2 ON e1.department = e2.department '
        'WHERE e1.id < :x LIMIT :lim',
        {'x': 99999, 'lim': 1000},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 7. Three-table JOIN (customer -> order -> order_item)
# ---------------------------------------------------------------------------
def test_three_table_join_differential(app_context):
    qs = {
        'tables': [
            {'id': 'c', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'o', 'tableName': 'order', 'alias': 'o'},
            {'id': 'oi', 'tableName': 'order_item', 'alias': 'oi'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER',
             'leftTableId': 'c', 'leftColumn': 'id',
             'rightTableId': 'o', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
            {'id': 'j2', 'type': 'INNER',
             'leftTableId': 'o', 'leftColumn': 'id',
             'rightTableId': 'oi', 'rightColumn': 'order_id',
             'leftTable': 'order', 'rightTable': 'order_item'},
        ],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'first_name'},
            {'tableId': 'o', 'columnName': 'id'},
            {'tableId': 'oi', 'columnName': 'quantity'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 500,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.first_name, o.id, oi.quantity '
        'FROM customer c '
        'INNER JOIN "order" o ON c.id = o.customer_id '
        'INNER JOIN order_item oi ON o.id = oi.order_id '
        'LIMIT :lim',
        {'lim': 500},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 8. Duplicate column names (id appears in multiple tables)
# ---------------------------------------------------------------------------
def test_duplicate_column_names_differential(app_context):
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
            {'tableId': 'c', 'columnName': 'id', 'alias': 'customer_id'},
            {'tableId': 'o', 'columnName': 'id', 'alias': 'order_id'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 50,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.id AS customer_id, o.id AS order_id '
        'FROM customer c INNER JOIN "order" o ON c.id = o.customer_id '
        'LIMIT :lim',
        {'lim': 50},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 9. NULL comparisons
# ---------------------------------------------------------------------------
def test_null_equality_differential(app_context):
    qs = {
        'tables': [{'id': 'e', 'tableName': 'employee', 'alias': 'e'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 'e', 'columnName': 'id'},
        ],
        'where': {
            'tableId': 'e', 'columnName': 'position',
            'cmp': '=', 'value': None,
        },
        'aggregations': [],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT e.id FROM employee e WHERE e.position IS NULL LIMIT :lim',
        {'lim': 100},
    )
    assert_same_rows(ast['rows'], hand)


def test_is_not_null_differential(app_context):
    qs = {
        'tables': [{'id': 'e', 'tableName': 'employee', 'alias': 'e'}],
        'joins': [],
        'selectedFields': [{'tableId': 'e', 'columnName': 'id'}],
        'where': {
            'tableId': 'e', 'columnName': 'position',
            'cmp': 'IS NOT NULL',
        },
        'aggregations': [],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT e.id FROM employee e WHERE e.position IS NOT NULL LIMIT :lim',
        {'lim': 100},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 10. Empty IN / NOT IN
# ---------------------------------------------------------------------------
def test_empty_in_differential(app_context):
    qs = {
        'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': {
            'tableId': 'c', 'columnName': 'country',
            'cmp': 'IN', 'value': [],
        },
        'aggregations': [],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.id FROM customer c WHERE 0 = 1 LIMIT :lim', {'lim': 100}
    )
    assert ast['rows'] == hand == []


def test_empty_not_in_differential(app_context):
    qs = {
        'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': {
            'tableId': 'c', 'columnName': 'country',
            'cmp': 'NOT IN', 'value': [],
        },
        'aggregations': [],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.id FROM customer c WHERE 1 = 1 LIMIT :lim', {'lim': 100}
    )
    assert len(ast['rows']) == len(hand)


# ---------------------------------------------------------------------------
# 11. Date comparison (parameter bound, not string-interpolated)
# ---------------------------------------------------------------------------
def test_date_comparison_differential(app_context):
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
            {'tableId': 'c', 'columnName': 'id'},
            {'tableId': 'o', 'columnName': 'order_date'},
        ],
        'where': {
            'tableId': 'o', 'columnName': 'order_date',
            'cmp': '>=', 'value': '2025-03-01',
        },
        'aggregations': [],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.id, o.order_date FROM customer c '
        'INNER JOIN "order" o ON c.id = o.customer_id '
        'WHERE o.order_date >= :d LIMIT :lim',
        {'d': '2025-03-01', 'lim': 100},
    )
    # Normalise dates for comparison (may come back as date objects / strings)
    norm = lambda rows: [(r[0], str(r[1])) for r in rows]
    assert_same_rows(norm(ast['rows']), norm(hand))


# ---------------------------------------------------------------------------
# 12. Pagination (LIMIT + OFFSET, both bound)
# ---------------------------------------------------------------------------
def test_pagination_differential(app_context):
    qs = {
        'tables': [{'id': 'c', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': None,
        'aggregations': [],
        'orderBy': [{'tableId': 'c', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 5,
        'offset': 3,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.id FROM customer c ORDER BY c.id ASC '
        'LIMIT :lim OFFSET :off',
        {'lim': 5, 'off': 3},
    )
    assert ast['rows'] == hand


# ---------------------------------------------------------------------------
# 13. CROSS JOIN
# ---------------------------------------------------------------------------
def test_cross_join_differential(app_context):
    qs = {
        'tables': [
            {'id': 'c', 'tableName': 'category', 'alias': 'c'},
            {'id': 's', 'tableName': 'supplier', 'alias': 's'},
        ],
        'joins': [{
            'id': 'j', 'type': 'CROSS',
            'leftTableId': 'c', 'leftColumn': 'id',
            'rightTableId': 's', 'rightColumn': 'id',
            'leftTable': 'category', 'rightTable': 'supplier',
        }],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'id'},
            {'tableId': 's', 'columnName': 'id'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 1000,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT c.id, s.id FROM category c CROSS JOIN supplier s LIMIT :lim',
        {'lim': 1000},
    )
    assert_same_rows(ast['rows'], hand)


# ---------------------------------------------------------------------------
# 14. COUNT aggregation
# ---------------------------------------------------------------------------
def test_count_aggregation_differential(app_context):
    qs = {
        'tables': [{'id': 'o', 'tableName': 'order', 'alias': 'o'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 'o', 'columnName': 'status'},
        ],
        'where': None,
        'aggregations': [
            {'tableId': 'o', 'columnName': 'id', 'function': 'COUNT',
             'alias': 'n'},
        ],
        'limit': 100,
    }
    ast = run_ast(qs)
    hand = run_handwritten(
        'SELECT o.status, COUNT(o.id) AS n FROM "order" o '
        'GROUP BY o.status LIMIT :lim',
        {'lim': 100},
    )
    ast_d = {r[0]: r[1] for r in ast['rows']}
    hand_d = {r[0]: r[1] for r in hand}
    assert ast_d == hand_d


# ---------------------------------------------------------------------------
# 15. Save / restore: serialize AST to JSON, re-parse it, and confirm the
#     re-loaded AST produces identical results.
# ---------------------------------------------------------------------------
def test_save_restore_roundtrip(app_context):
    import json
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
            {'tableId': 'c', 'columnName': 'first_name'},
            {'tableId': 'o', 'columnName': 'total_amount'},
        ],
        'where': {
            'op': 'AND',
            'children': [
                {'tableId': 'o', 'columnName': 'total_amount',
                 'cmp': '>', 'value': 50},
            ],
        },
        'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 20,
        'offset': 0,
    }
    first = QueryExecutor.execute(qs)
    restored = json.loads(json.dumps(qs))
    second = QueryExecutor.execute(restored)
    assert first['sql'] == second['sql']
    assert first['params'] == second['params']
    assert first['rows'] == second['rows']


# ---------------------------------------------------------------------------
# 16. API endpoint differential (through Flask test client)
# ---------------------------------------------------------------------------
def test_api_execute_endpoint_differential(client):
    qs = {
        'tables': [
            {'id': 'c', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'o', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [{
            'id': 'j', 'type': 'LEFT',
            'leftTableId': 'c', 'leftColumn': 'id',
            'rightTableId': 'o', 'rightColumn': 'customer_id',
            'leftTable': 'customer', 'rightTable': 'order',
        }],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'id'},
            {'tableId': 'o', 'columnName': 'id'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 100,
    }
    resp = client.post('/api/execute-query', json=qs)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    api_rows = resp.get_json()['rows']

    with client.application.app_context():
        hand = run_handwritten(
            'SELECT c.id, o.id FROM customer c '
            'LEFT JOIN "order" o ON c.id = o.customer_id LIMIT :lim',
            {'lim': 100},
        )
    assert_same_rows(api_rows, hand, labels=('api', 'hand'))


def test_api_rejects_right_join(client):
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
        'limit': 10,
    }
    resp = client.post('/api/generate-sql', json=qs)
    assert resp.status_code == 400
    assert 'not supported by SQLite' in resp.get_json()['error']
