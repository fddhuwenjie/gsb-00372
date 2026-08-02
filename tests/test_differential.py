"""Differential tests: every query built through the unified AST / SQLGenerator
is executed and its results are compared, row for row, against an equivalent
hand-written parameterized SQL statement run directly on the same SQLite
database. This proves the generator's semantics match plain SQL.

Coverage: self-join, three-table join, duplicate column names, NULLs, dates,
aggregation + HAVING, pagination (LIMIT/OFFSET) and save/restore round-trip.
"""
import json
from app.services.query_executor import QueryExecutor


def tables(*specs):
    return [{'id': tid, 'tableName': name, 'alias': alias, 'position': {}}
            for tid, name, alias in specs]


def run_generated(app, qs):
    with app.app_context():
        res = QueryExecutor.execute(qs, max_rows=1000)
    return res['rows'], [c['name'] for c in res['columns']]


def run_reference(conn, sql, params):
    cur = conn.execute(sql, params)
    rows = [list(r) for r in cur.fetchall()]
    return rows, [d[0] for d in cur.description]


def assert_same(app, conn, qs, ref_sql, ref_params):
    gen_rows, _ = run_generated(app, qs)
    ref_rows, _ = run_reference(conn, ref_sql, ref_params)
    assert gen_rows == ref_rows


# 1. Self-join ---------------------------------------------------------------
def test_diff_self_join(app, sqlite_conn):
    qs = {
        'tables': tables(('a', 'order', 'o1'), ('b', 'order', 'o2')),
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'a', 'leftColumn': 'customer_id',
                   'rightTableId': 'b', 'rightColumn': 'customer_id', 'leftTable': 'order',
                   'rightTable': 'order'}],
        'selectedFields': [{'tableId': 'a', 'columnName': 'id'},
                           {'tableId': 'b', 'columnName': 'id'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c', 'tableId': 'a', 'columnName': 'id', 'cmp': '<', 'value': 5}]},
        'orderBy': [{'tableId': 'a', 'columnName': 'id', 'direction': 'ASC'},
                    {'tableId': 'b', 'columnName': 'id', 'direction': 'ASC'}],
        'aggregations': [], 'limit': 100,
    }
    ref = ('SELECT o1.id, o2.id FROM "order" o1 '
           'INNER JOIN "order" o2 ON o1.customer_id = o2.customer_id '
           'WHERE o1.id < :p1 ORDER BY o1.id ASC, o2.id ASC LIMIT :p2')
    assert_same(app, sqlite_conn, qs, ref, {'p1': 5, 'p2': 100})


# 2. Three-table join --------------------------------------------------------
def test_diff_three_table_join(app, sqlite_conn):
    qs = {
        'tables': tables(('c', 'customer', 'c'), ('o', 'order', 'o'), ('e', 'employee', 'e')),
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
             'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'},
            {'id': 'j2', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'employee_id',
             'rightTableId': 'e', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'employee'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'first_name'},
                           {'tableId': 'e', 'columnName': 'last_name'},
                           {'tableId': 'o', 'columnName': 'id'}],
        'where': None, 'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100,
    }
    ref = ('SELECT c.first_name, e.last_name, o.id FROM "order" o '
           'INNER JOIN customer c ON o.customer_id = c.id '
           'INNER JOIN employee e ON o.employee_id = e.id '
           'ORDER BY o.id ASC LIMIT :p1')
    assert_same(app, sqlite_conn, qs, ref, {'p1': 100})


# 3. Duplicate column names across tables -----------------------------------
def test_diff_duplicate_column_names(app, sqlite_conn):
    # customer.first_name and employee.first_name both selected; aliases keep
    # them distinct and bound to the right table instance.
    qs = {
        'tables': tables(('c', 'customer', 'c'), ('o', 'order', 'o'), ('e', 'employee', 'e')),
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
             'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'},
            {'id': 'j2', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'employee_id',
             'rightTableId': 'e', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'employee'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'first_name', 'alias': 'cust_first'},
                           {'tableId': 'e', 'columnName': 'first_name', 'alias': 'emp_first'}],
        'where': None, 'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 5,
    }
    gen_rows, cols = run_generated(app, qs)
    assert cols == ['cust_first', 'emp_first']
    ref = ('SELECT c.first_name AS cust_first, e.first_name AS emp_first FROM "order" o '
           'INNER JOIN customer c ON o.customer_id = c.id '
           'INNER JOIN employee e ON o.employee_id = e.id '
           'ORDER BY o.id ASC LIMIT :p1')
    ref_rows, _ = run_reference(sqlite_conn, ref, {'p1': 5})
    assert gen_rows == ref_rows


# 4. NULLs (LEFT JOIN + IS NULL) --------------------------------------------
def test_diff_nulls_left_join(app, sqlite_conn):
    qs = {
        'tables': tables(('c', 'customer', 'c'), ('o', 'order', 'o')),
        'joins': [{'id': 'j', 'type': 'LEFT', 'leftTableId': 'c', 'leftColumn': 'id',
                   'rightTableId': 'o', 'rightColumn': 'customer_id', 'leftTable': 'customer',
                   'rightTable': 'order'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'a', 'tableId': 'o', 'columnName': 'id', 'cmp': 'IS NULL'}]},
        'aggregations': [],
        'orderBy': [{'tableId': 'c', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100,
    }
    ref = ('SELECT c.id FROM customer c LEFT JOIN "order" o ON c.id = o.customer_id '
           'WHERE o.id IS NULL ORDER BY c.id ASC LIMIT :p1')
    assert_same(app, sqlite_conn, qs, ref, {'p1': 100})


# 5. Dates -------------------------------------------------------------------
def test_diff_date_comparison(app, sqlite_conn):
    qs = {
        'tables': tables(('o', 'order', 'o')),
        'joins': [],
        'selectedFields': [{'tableId': 'o', 'columnName': 'id'},
                           {'tableId': 'o', 'columnName': 'order_date'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'a', 'tableId': 'o', 'columnName': 'order_date', 'cmp': '>=', 'value': '2025-03-01'},
            {'id': 'b', 'tableId': 'o', 'columnName': 'order_date', 'cmp': '<', 'value': '2025-04-01'}]},
        'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'order_date', 'direction': 'ASC'}],
        'limit': 100,
    }
    ref = ('SELECT o.id, o.order_date FROM "order" o '
           'WHERE o.order_date >= :p1 AND o.order_date < :p2 '
           'ORDER BY o.order_date ASC LIMIT :p3')
    assert_same(app, sqlite_conn, qs, ref,
                {'p1': '2025-03-01', 'p2': '2025-04-01', 'p3': 100})


# 6. Aggregation + HAVING ----------------------------------------------------
def test_diff_aggregation_having(app, sqlite_conn):
    qs = {
        'tables': tables(('o', 'order', 'o'), ('c', 'customer', 'c')),
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
                   'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'}],
        'aggregations': [{'tableId': 'o', 'columnName': 'total_amount', 'function': 'SUM', 'alias': 'total'}],
        'having': {'id': 'h', 'op': 'AND', 'children': [
            {'id': 'hc', 'tableId': 'o', 'columnName': 'total_amount', 'cmp': '>', 'value': 200, 'function': 'SUM'}]},
        'where': None,
        'orderBy': [{'tableId': 'c', 'columnName': 'country', 'direction': 'ASC'}],
        'limit': 100,
    }
    ref = ('SELECT c.country, SUM(o.total_amount) AS total FROM "order" o '
           'INNER JOIN customer c ON o.customer_id = c.id '
           'GROUP BY c.country HAVING SUM(o.total_amount) > :p1 '
           'ORDER BY c.country ASC LIMIT :p2')
    assert_same(app, sqlite_conn, qs, ref, {'p1': 200, 'p2': 100})


# 7. Pagination (LIMIT + OFFSET) --------------------------------------------
def test_diff_pagination(app, sqlite_conn):
    qs = {
        'tables': tables(('p', 'product', 'p')),
        'joins': [],
        'selectedFields': [{'tableId': 'p', 'columnName': 'id'},
                           {'tableId': 'p', 'columnName': 'name'}],
        'where': None, 'aggregations': [],
        'orderBy': [{'tableId': 'p', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 3, 'offset': 4,
    }
    ref = 'SELECT p.id, p.name FROM product p ORDER BY p.id ASC LIMIT :p1 OFFSET :p2'
    assert_same(app, sqlite_conn, qs, ref, {'p1': 3, 'p2': 4})


# 8. IN with values ----------------------------------------------------------
def test_diff_in_list(app, sqlite_conn):
    qs = {
        'tables': tables(('c', 'customer', 'c')),
        'joins': [],
        'selectedFields': [{'tableId': 'c', 'columnName': 'id'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'a', 'tableId': 'c', 'columnName': 'country', 'cmp': 'IN',
             'value': ['US', 'UK']}]},
        'aggregations': [],
        'orderBy': [{'tableId': 'c', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100,
    }
    ref = ('SELECT c.id FROM customer c WHERE c.country IN (:p1, :p2) '
           'ORDER BY c.id ASC LIMIT :p3')
    assert_same(app, sqlite_conn, qs, ref, {'p1': 'US', 'p2': 'UK', 'p3': 100})


# 9. Save / restore round-trip through JSON ---------------------------------
def test_diff_save_restore_roundtrip(app, sqlite_conn):
    qs = {
        'tables': tables(('o', 'order', 'o'), ('c', 'customer', 'c')),
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
                   'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'},
                           {'tableId': 'o', 'columnName': 'total_amount'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'a', 'tableId': 'o', 'columnName': 'total_amount', 'cmp': '>', 'value': 100}]},
        'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 50,
    }
    # Simulate persistence: serialize to JSON and back, exactly like save/reopen.
    restored = json.loads(json.dumps(qs))
    before, _ = run_generated(app, qs)
    after, _ = run_generated(app, restored)
    assert before == after
    ref = ('SELECT c.country, o.total_amount FROM "order" o '
           'INNER JOIN customer c ON o.customer_id = c.id '
           'WHERE o.total_amount > :p1 ORDER BY o.id ASC LIMIT :p2')
    ref_rows, _ = run_reference(sqlite_conn, ref, {'p1': 100, 'p2': 50})
    assert after == ref_rows
