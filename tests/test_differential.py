"""Differential tests: every constructed AST query is compared against an
equivalent hand-written parameterized SQL statement on the same temporary
SQLite database. Column names and result rows must match exactly.

Coverage: self-joins, three-table JOINs, duplicate column names, NULL
semantics, dates, aggregations + HAVING, pagination, nested AND/OR/NOT,
empty IN/NOT IN, LIKE, LEFT JOIN null extension, CROSS JOIN, subqueries,
CTEs, and save/reopen + share/restore round trips.
"""
from collections import Counter

import pytest
from sqlalchemy import text

from app.services.query_executor import QueryExecutor
from tests.helpers import run_reference


def execute_ast(app, query):
    with app.app_context():
        return QueryExecutor.execute(query)


def assert_results_match(app, connection, query, ref_sql, ref_params=None, ordered=False):
    result = execute_ast(app, query)
    ref_columns, ref_rows = run_reference(connection, ref_sql, ref_params)

    got_columns = [c['name'] for c in result['columns']]
    assert got_columns == ref_columns, (
        f'column mismatch:\n  got: {got_columns}\n  ref: {ref_columns}'
    )

    got_rows = [tuple(r) for r in result['rows']]
    ref_rows = [tuple(r) for r in ref_rows]
    if ordered:
        assert got_rows == ref_rows
    else:
        assert Counter(got_rows) == Counter(ref_rows), (
            f'row mismatch (multiset):\n'
            f'  only in AST: {list((Counter(got_rows) - Counter(ref_rows)).elements())[:5]}\n'
            f'  only in ref: {list((Counter(ref_rows) - Counter(got_rows)).elements())[:5]}'
        )
    return result


# ----------------------------------------------------------------------
# Differential cases
# ----------------------------------------------------------------------

def test_single_table_where(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't1', 'columnName': 'country'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
        ]},
        'aggregations': [],
        'limit': 100,
    }
    assert_results_match(
        app, connection, query,
        'SELECT first_name, country FROM customer WHERE country = :v1 LIMIT :lim',
        {'v1': 'US', 'lim': 100},
    )


def test_self_join(app, connection):
    query = {
        'tables': [
            {'id': 'e1', 'tableName': 'employee', 'alias': 'e'},
            {'id': 'e2', 'tableName': 'employee', 'alias': 'm'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'LEFT', 'leftTableId': 'e1', 'leftColumn': 'id',
             'rightTableId': 'e2', 'rightColumn': 'id',
             'leftTable': 'employee', 'rightTable': 'employee'},
        ],
        'selectedFields': [
            {'tableId': 'e1', 'columnName': 'first_name'},
            {'tableId': 'e2', 'columnName': 'first_name'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 100,
    }
    assert_results_match(
        app, connection, query,
        'SELECT e.first_name AS e_first_name, m.first_name AS m_first_name '
        'FROM employee e LEFT JOIN employee m ON e.id = m.id LIMIT :lim',
        {'lim': 100},
    )


def test_three_table_join(app, connection):
    query = {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'order', 'alias': 'o'},
            {'id': 't3', 'tableName': 'order_item', 'alias': 'oi'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'id',
             'rightTableId': 't2', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
            {'id': 'j2', 'type': 'INNER', 'leftTableId': 't2', 'leftColumn': 'id',
             'rightTableId': 't3', 'rightColumn': 'order_id',
             'leftTable': 'order', 'rightTable': 'order_item'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'country'},
            {'tableId': 't2', 'columnName': 'total_amount'},
            {'tableId': 't3', 'columnName': 'quantity'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't3', 'columnName': 'quantity', 'cmp': '>=', 'value': 2},
        ]},
        'aggregations': [],
        'limit': 1000,
    }
    assert_results_match(
        app, connection, query,
        'SELECT c.country, o.total_amount, oi.quantity '
        'FROM customer c '
        'INNER JOIN "order" o ON c.id = o.customer_id '
        'INNER JOIN order_item oi ON o.id = oi.order_id '
        'WHERE oi.quantity >= :v1 LIMIT :lim',
        {'v1': 2, 'lim': 1000},
    )


def test_duplicate_column_names(app, connection):
    query = {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'id',
             'rightTableId': 't2', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't2', 'columnName': 'id'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 100,
    }
    result = assert_results_match(
        app, connection, query,
        'SELECT c.id AS c_id, o.id AS o_id FROM customer c '
        'INNER JOIN "order" o ON c.id = o.customer_id LIMIT :lim',
        {'lim': 100},
    )
    assert [c['name'] for c in result['columns']] == ['c_id', 'o_id']


def test_null_semantics(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'supplier', 'alias': 's'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'name'},
            {'tableId': 't1', 'columnName': 'contact_name'},
        ],
        'where': {'id': 'w', 'op': 'OR', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'contact_name', 'cmp': 'IS NULL'},
            {'id': 'c2', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': None},
        ]},
        'aggregations': [],
        'limit': 100,
    }
    result = assert_results_match(
        app, connection, query,
        'SELECT name, contact_name FROM supplier '
        'WHERE contact_name IS NULL OR country IS NULL LIMIT :lim',
        {'lim': 100},
    )
    assert result['rowCount'] >= 1  # the fixture inserted a NULL-row supplier


def test_date_filter(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'order', 'alias': 'o'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't1', 'columnName': 'order_date'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'order_date', 'cmp': '>=', 'value': '2025-04-01'},
            {'id': 'c2', 'tableId': 't1', 'columnName': 'order_date', 'cmp': '<', 'value': '2025-05-01'},
        ]},
        'aggregations': [],
        'limit': 100,
    }
    assert_results_match(
        app, connection, query,
        'SELECT id, order_date FROM "order" '
        'WHERE order_date >= :d1 AND order_date < :d2 LIMIT :lim',
        {'d1': '2025-04-01', 'd2': '2025-05-01', 'lim': 100},
    )


def test_aggregation_with_having(app, connection):
    query = {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'id',
             'rightTableId': 't2', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'country'},
        ],
        'where': None,
        'aggregations': [
            {'tableId': 't2', 'columnName': 'id', 'function': 'COUNT', 'alias': 'n'},
            {'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM', 'alias': 'total'},
        ],
        'having': {'id': 'h', 'op': 'AND', 'children': [
            {'id': 'h1', 'tableId': 't2', 'columnName': 'total_amount',
             'function': 'SUM', 'cmp': '>', 'value': 500},
        ]},
        'limit': 100,
    }
    assert_results_match(
        app, connection, query,
        'SELECT c.country, COUNT(o.id) AS n, SUM(o.total_amount) AS total '
        'FROM customer c INNER JOIN "order" o ON c.id = o.customer_id '
        'GROUP BY c.country HAVING SUM(o.total_amount) > :v1 LIMIT :lim',
        {'v1': 500, 'lim': 100},
    )


def test_pagination(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
        'where': None,
        'aggregations': [],
        'limit': 3,
        'offset': 2,
    }
    result = assert_results_match(
        app, connection, query,
        'SELECT id FROM customer LIMIT :lim OFFSET :off',
        {'lim': 3, 'off': 2},
        ordered=True,
    )
    assert result['params'] == {'p1': 3, 'p2': 2}


def test_nested_and_or_not(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't1', 'columnName': 'city'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'g', 'op': 'OR', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                {'id': 'c2', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'UK'},
            ]},
            {'id': 'n', 'op': 'NOT', 'children': [
                {'id': 'c3', 'tableId': 't1', 'columnName': 'city', 'cmp': '=', 'value': 'London'},
            ]},
        ]},
        'aggregations': [],
        'limit': 100,
    }
    assert_results_match(
        app, connection, query,
        "SELECT first_name, city FROM customer "
        "WHERE (country = :v1 OR country = :v2) AND NOT (city = :v3) LIMIT :lim",
        {'v1': 'US', 'v2': 'UK', 'v3': 'London', 'lim': 100},
    )


def test_empty_in_and_not_in(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'NOT IN', 'value': []},
            {'id': 'g', 'op': 'OR', 'children': [
                {'id': 'c2', 'tableId': 't1', 'columnName': 'id', 'cmp': 'IN', 'value': []},
                {'id': 'c3', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'Spain'},
            ]},
        ]},
        'aggregations': [],
        'limit': 100,
    }
    assert_results_match(
        app, connection, query,
        "SELECT id FROM customer WHERE (1 = 1) AND ((1 = 0) OR country = :v1) LIMIT :lim",
        {'v1': 'Spain', 'lim': 100},
    )


def test_in_and_like_parameters(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't1', 'columnName': 'last_name'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN',
             'value': ['US', 'Germany']},
            {'id': 'c2', 'tableId': 't1', 'columnName': 'first_name', 'cmp': 'LIKE', 'value': 'A%'},
        ]},
        'aggregations': [],
        'limit': 100,
    }
    assert_results_match(
        app, connection, query,
        "SELECT first_name, last_name FROM customer "
        "WHERE country IN (:v1, :v2) AND first_name LIKE :v3 LIMIT :lim",
        {'v1': 'US', 'v2': 'Germany', 'v3': 'A%', 'lim': 100},
    )


def test_left_join_null_extension(app, connection):
    query = {
        'tables': [
            {'id': 't1', 'tableName': 'order', 'alias': 'o'},
            {'id': 't2', 'tableName': 'employee', 'alias': 'e'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'LEFT', 'leftTableId': 't1', 'leftColumn': 'employee_id',
             'rightTableId': 't2', 'rightColumn': 'id',
             'leftTable': 'order', 'rightTable': 'employee'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't2', 'columnName': 'first_name'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 1000,
    }
    result = assert_results_match(
        app, connection, query,
        'SELECT o.id, e.first_name FROM "order" o '
        'LEFT JOIN employee e ON o.employee_id = e.id LIMIT :lim',
        {'lim': 1000},
    )
    # the fixture inserted one order with employee_id = NULL
    assert any(row[1] is None for row in result['rows'])


def test_cross_join(app, connection):
    query = {
        'tables': [
            {'id': 't1', 'tableName': 'category', 'alias': 'ca'},
            {'id': 't2', 'tableName': 'supplier', 'alias': 's'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'CROSS', 'leftTableId': 't1', 'rightTableId': 't2',
             'leftTable': 'category', 'rightTable': 'supplier'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'name'},
            {'tableId': 't2', 'columnName': 'name'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 1000,
    }
    assert_results_match(
        app, connection, query,
        'SELECT ca.name AS ca_name, s.name AS s_name '
        'FROM category ca CROSS JOIN supplier s LIMIT :lim',
        {'lim': 1000},
    )


def test_in_subquery(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't1', 'columnName': 'last_name'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'id', 'cmp': 'IN',
             'subquery': {
                 'tables': [{'id': 's1', 'tableName': 'order', 'alias': 'o'}],
                 'joins': [],
                 'selectedFields': [{'tableId': 's1', 'columnName': 'customer_id'}],
                 'where': {'id': 'sw', 'op': 'AND', 'children': [
                     {'id': 'sc', 'tableId': 's1', 'columnName': 'status', 'cmp': '=', 'value': 'shipped'},
                 ]},
                 'aggregations': [],
                 'limit': 1000}},
        ]},
        'aggregations': [],
        'limit': 100,
    }
    assert_results_match(
        app, connection, query,
        'SELECT first_name, last_name FROM customer WHERE id IN '
        '(SELECT customer_id FROM "order" WHERE status = :v1 LIMIT :sublim) LIMIT :lim',
        {'v1': 'shipped', 'sublim': 1000, 'lim': 100},
    )


def test_cte_query(app, connection):
    query = {
        'tables': [{'id': 't1', 'tableName': 'big_orders', 'alias': 'b'}],
        'joins': [],
        'selectedFields': [{'tableId': 't1', 'columnName': 'customer_id'}],
        'where': None,
        'aggregations': [],
        'limit': 100,
        'ctes': [{
            'id': 'cte1',
            'name': 'big_orders',
            'queryStructure': {
                'tables': [{'id': 's1', 'tableName': 'order', 'alias': 'o'}],
                'joins': [],
                'selectedFields': [{'tableId': 's1', 'columnName': 'customer_id'}],
                'where': {'id': 'sw', 'op': 'AND', 'children': [
                    {'id': 'sc', 'tableId': 's1', 'columnName': 'total_amount', 'cmp': '>', 'value': 200},
                ]},
                'aggregations': [],
                'limit': 1000},
        }],
    }
    assert_results_match(
        app, connection, query,
        'WITH big_orders AS (SELECT customer_id FROM "order" WHERE total_amount > :v1 LIMIT :sublim) '
        'SELECT b.customer_id FROM big_orders b LIMIT :lim',
        {'v1': 200, 'sublim': 1000, 'lim': 100},
    )


# ----------------------------------------------------------------------
# Save/reopen and share/restore differential round trips
# ----------------------------------------------------------------------

def _complex_query():
    return {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c',
             'position': {'x': 0, 'y': 0}},
            {'id': 't2', 'tableName': 'order', 'alias': 'o',
             'position': {'x': 200, 'y': 0}},
            {'id': 't3', 'tableName': 'order_item', 'alias': 'oi',
             'position': {'x': 400, 'y': 0}},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'id',
             'rightTableId': 't2', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
            {'id': 'j2', 'type': 'LEFT', 'leftTableId': 't2', 'leftColumn': 'id',
             'rightTableId': 't3', 'rightColumn': 'order_id',
             'leftTable': 'order', 'rightTable': 'order_item'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't2', 'columnName': 'id'},
            {'tableId': 't1', 'columnName': 'country'},
            {'tableId': 't3', 'columnName': 'quantity'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't2', 'columnName': 'status', 'cmp': 'IN',
             'value': ['completed', 'shipped']},
        ]},
        'aggregations': [],
        'limit': 500,
    }


_REFERENCE_SQL = (
    'SELECT c.id AS c_id, o.id AS o_id, c.country, oi.quantity '
    'FROM customer c '
    'INNER JOIN "order" o ON c.id = o.customer_id '
    'LEFT JOIN order_item oi ON o.id = oi.order_id '
    "WHERE o.status IN (:v1, :v2) LIMIT :lim"
)
_REFERENCE_PARAMS = {'v1': 'completed', 'v2': 'shipped', 'lim': 500}


def _assert_rows_match_reference(connection, result):
    ref_columns, ref_rows = run_reference(connection, _REFERENCE_SQL, _REFERENCE_PARAMS)
    assert [c['name'] for c in result['columns']] == ref_columns
    assert Counter(tuple(r) for r in result['rows']) == Counter(tuple(r) for r in ref_rows)


def test_save_reopen_roundtrip(app, client, connection):
    created = client.post('/api/queries', json={
        'name': 'differential-save',
        'query_structure': _complex_query(),
    })
    assert created.status_code == 201
    saved_id = created.get_json()['id']

    # simulate reopen: fetch the stored structure back and execute it
    reopened = client.get(f'/api/queries/{saved_id}').get_json()['query_structure']
    result = execute_ast(app, reopened)
    _assert_rows_match_reference(connection, result)


def test_share_restore_roundtrip(app, client, connection):
    created = client.post('/api/queries', json={
        'name': 'differential-share',
        'query_structure': _complex_query(),
    })
    saved_id = created.get_json()['id']

    token = client.post(f'/api/queries/{saved_id}/share', json={}).get_json()['token']
    payload = client.get(f'/api/share/{token}').get_json()

    # the shared payload restores the identical AST and executes it server-side
    assert payload['query']['query_structure']['tables'][0]['id'] == 't1'
    _assert_rows_match_reference(connection, payload['result'])
