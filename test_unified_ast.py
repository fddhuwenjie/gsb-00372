"""
Unified AST round-trip tests and API differential tests.

Each constructed query AST is:
1. Sent to the backend to generate SQL + params
2. Executed via the API
3. Compared with an equivalent handwritten parameterized SQL executed directly on SQLite

Covers: self-join, three-table JOIN, duplicate column names, null values,
dates, aggregation, HAVING, ORDER BY, pagination (LIMIT/OFFSET), CROSS JOIN,
NOT conditions, IS NULL, empty IN/NOT IN, save/restore.
"""
import pytest
from sqlalchemy import text
from app.services.sql_generator import SQLGenerator
from app.services.security_service import SecurityService
from app.services.query_executor import QueryExecutor


def _normalize_rows(rows):
    return sorted(tuple(r) for r in rows)


def _run_handwritten(db_connection, sql, params=None):
    result = db_connection.execute(text(sql), params or {})
    return [list(row) for row in result.fetchall()]


def _run_ast(db_connection, query_structure):
    result = QueryExecutor.generate_sql(query_structure)
    sql = result['sql']
    params = result['params']
    SecurityService.validate_readonly_sql(sql)
    rows = db_connection.execute(text(sql), params).fetchall()
    return [list(row) for row in rows], sql, params


def _assert_results_equal(ast_rows, hand_rows, label=""):
    ast_set = _normalize_rows(ast_rows)
    hand_set = _normalize_rows(hand_rows)
    assert ast_set == hand_set, (
        f"{label}: result mismatch.\n"
        f"AST rows ({len(ast_set)}): {list(ast_set)[:5]}...\n"
        f"Hand rows ({len(hand_set)}): {list(hand_set)[:5]}..."
    )


class TestSQLGeneratorUnit:
    def test_simple_select_all(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'cu'}],
            'joins': [],
            'selectedFields': [],
            'where': None,
            'having': None,
            'aggregations': [],
            'orderBy': [],
            'limit': 10,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        params = gen.get_params()
        assert 'SELECT *' in sql
        assert 'FROM "customer" "cu"' in sql
        assert 'LIMIT :p1' in sql
        assert params['p1'] == 10

    def test_inner_join(self):
        query = {
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
                {'tableId': 't1', 'columnName': 'first_name'},
                {'tableId': 't2', 'columnName': 'total_amount'},
            ],
            'where': None,
            'having': None,
            'aggregations': [],
            'orderBy': [],
            'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'INNER JOIN "order" "o"' in sql
        assert '"c"."id" = "o"."customer_id"' in sql

    def test_left_join(self):
        query = {
            'tables': [
                {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
                {'id': 't2', 'tableName': 'order', 'alias': 'o'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'LEFT',
                'leftTableId': 't1', 'leftColumn': 'id',
                'rightTableId': 't2', 'rightColumn': 'customer_id',
                'leftTable': 'customer', 'rightTable': 'order',
            }],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'LEFT JOIN' in sql

    def test_cross_join(self):
        query = {
            'tables': [
                {'id': 't1', 'tableName': 'category', 'alias': 'ca'},
                {'id': 't2', 'tableName': 'supplier', 'alias': 'su'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'CROSS',
                'leftTableId': 't1', 'leftColumn': '',
                'rightTableId': 't2', 'rightColumn': '',
                'leftTable': 'category', 'rightTable': 'supplier',
            }],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'name'},
                {'tableId': 't2', 'columnName': 'name'},
            ],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 1000,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'CROSS JOIN "supplier" "su"' in sql
        assert 'ON' not in sql

    def test_right_join_rejected(self):
        query = {
            'tables': [
                {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
                {'id': 't2', 'tableName': 'order', 'alias': 'o'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'RIGHT',
                'leftTableId': 't1', 'leftColumn': 'id',
                'rightTableId': 't2', 'rightColumn': 'customer_id',
                'leftTable': 'customer', 'rightTable': 'order',
            }],
            'selectedFields': [], 'where': None, 'having': None,
            'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        with pytest.raises(ValueError, match='RIGHT JOIN is not supported'):
            SQLGenerator(query).generate()

    def test_full_join_rejected(self):
        query = {
            'tables': [
                {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
                {'id': 't2', 'tableName': 'order', 'alias': 'o'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'FULL',
                'leftTableId': 't1', 'leftColumn': 'id',
                'rightTableId': 't2', 'rightColumn': 'customer_id',
                'leftTable': 'customer', 'rightTable': 'order',
            }],
            'selectedFields': [], 'where': None, 'having': None,
            'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        with pytest.raises(ValueError, match='FULL JOIN is not supported'):
            SQLGenerator(query).generate()

    def test_nested_and_or_conditions(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                    {'id': 'g1', 'op': 'OR', 'children': [
                        {'id': 'c2', 'tableId': 't1', 'columnName': 'city', 'cmp': '=', 'value': 'New York'},
                        {'id': 'c3', 'tableId': 't1', 'columnName': 'city', 'cmp': '=', 'value': 'Chicago'},
                    ]},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        params = gen.get_params()
        assert 'WHERE' in sql
        assert 'AND' in sql
        assert 'OR' in sql
        assert params['p1'] == 'US'

    def test_not_condition(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'NOT', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'NOT (' in sql

    def test_is_null(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'email', 'cmp': 'IS NULL'},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'IS NULL' in sql
        assert ':p' not in sql.split('WHERE')[1].split('LIMIT')[0]

    def test_is_not_null(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'email', 'cmp': 'IS NOT NULL'},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'IS NOT NULL' in sql

    def test_empty_in(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN', 'value': []},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert '1 = 0' in sql

    def test_empty_not_in(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'NOT IN', 'value': []},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert '1 = 1' in sql

    def test_in_with_values(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN', 'value': ['US', 'UK', 'Germany']},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        params = gen.get_params()
        assert 'IN (' in sql
        assert len([k for k in params if k.startswith('p')]) >= 4

    def test_aggregation_with_group_by(self):
        query = {
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
            'selectedFields': [{'tableId': 't1', 'columnName': 'country'}],
            'where': None, 'having': None,
            'aggregations': [
                {'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM', 'alias': 'total'},
            ],
            'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'SUM(' in sql
        assert 'GROUP BY' in sql
        assert '"c"."country"' in sql

    def test_having_clause(self):
        query = {
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
            'selectedFields': [{'tableId': 't1', 'columnName': 'country'}],
            'where': None,
            'having': {
                'id': 'h1', 'op': 'AND', 'children': [
                    {'id': 'hc1', 'tableId': 't2', 'columnName': 'total_amount', 'cmp': '>', 'value': 500},
                ],
            },
            'aggregations': [
                {'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM', 'alias': 'total'},
            ],
            'orderBy': [], 'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'HAVING' in sql

    def test_order_by(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'first_name'},
            ],
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [
                {'tableId': 't1', 'columnName': 'first_name', 'direction': 'ASC'},
                {'tableId': 't1', 'columnName': 'id', 'direction': 'DESC'},
            ],
            'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert 'ORDER BY' in sql
        assert 'ASC' in sql
        assert 'DESC' in sql

    def test_limit_offset_parameterized(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 10,
            'offset': 5,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        params = gen.get_params()
        assert 'LIMIT :p1' in sql
        assert 'OFFSET :p2' in sql
        assert params['p1'] == 10
        assert params['p2'] == 5

    def test_self_join(self):
        query = {
            'tables': [
                {'id': 't1', 'tableName': 'employee', 'alias': 'e1'},
                {'id': 't2', 'tableName': 'employee', 'alias': 'e2'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'INNER',
                'leftTableId': 't1', 'leftColumn': 'id',
                'rightTableId': 't2', 'rightColumn': 'id',
                'leftTable': 'employee', 'rightTable': 'employee',
            }],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'first_name', 'alias': 'emp1'},
                {'tableId': 't2', 'columnName': 'first_name', 'alias': 'emp2'},
            ],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 100,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert '"e1"' in sql
        assert '"e2"' in sql
        assert 'AS "emp1"' in sql
        assert 'AS "emp2"' in sql

    def test_duplicate_column_names_disambiguated(self):
        query = {
            'tables': [
                {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
                {'id': 't2', 'tableName': 'employee', 'alias': 'e'},
            ],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't2', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'first_name'},
                {'tableId': 't2', 'columnName': 'first_name'},
            ],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 5,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        assert '"c"."id"' in sql
        assert '"e"."id"' in sql
        assert '"c"."first_name"' in sql
        assert '"e"."first_name"' in sql

    def test_all_values_parameterized(self):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                    {'id': 'c2', 'tableId': 't1', 'columnName': 'id', 'cmp': '>', 'value': 3},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 10, 'offset': 0,
        }
        gen = SQLGenerator(query)
        sql = gen.generate()
        params = gen.get_params()
        assert "'US'" not in sql
        assert params['p1'] == 'US'
        assert params['p2'] == 3
        assert params['p3'] == 10
        assert params['p4'] == 0
        where_clause = sql.split('WHERE')[1].split('LIMIT')[0]
        assert ':p1' in where_clause
        assert ':p2' in where_clause


class TestSecurity:
    def test_reject_insert(self):
        with pytest.raises(ValueError, match='Write operations'):
            SecurityService.validate_readonly_sql('INSERT INTO customer VALUES (1)')

    def test_reject_update(self):
        with pytest.raises(ValueError, match='Write operations'):
            SecurityService.validate_readonly_sql('UPDATE customer SET name = 1')

    def test_reject_delete(self):
        with pytest.raises(ValueError, match='Write operations'):
            SecurityService.validate_readonly_sql('DELETE FROM customer')

    def test_reject_drop(self):
        with pytest.raises(ValueError, match='Write operations'):
            SecurityService.validate_readonly_sql('DROP TABLE customer')

    def test_reject_comment_line(self):
        with pytest.raises(ValueError, match='comments'):
            SecurityService.validate_readonly_sql('SELECT * FROM customer -- evil')

    def test_reject_comment_block(self):
        with pytest.raises(ValueError, match='comments'):
            SecurityService.validate_readonly_sql('SELECT * FROM customer /* evil */')

    def test_reject_multi_statement(self):
        with pytest.raises(ValueError, match='Multiple SQL|Write operations'):
            SecurityService.validate_readonly_sql('SELECT * FROM customer; SELECT * FROM category;')

    def test_reject_dangerous_pragma(self):
        with pytest.raises(ValueError, match='PRAGMA'):
            SecurityService.validate_readonly_sql('PRAGMA writable_schema = 1')

    def test_allow_select(self):
        assert SecurityService.validate_readonly_sql('SELECT * FROM customer') is True

    def test_allow_with_cte(self):
        assert SecurityService.validate_readonly_sql('WITH cte AS (SELECT 1) SELECT * FROM cte') is True

    def test_reject_non_select(self):
        with pytest.raises(ValueError, match='Only SELECT'):
            SecurityService.validate_readonly_sql('PRAGMA table_info(customer)')

    def test_quoted_identifier_not_flagged(self):
        sql = 'SELECT "insert_log" FROM "update_table"'
        assert SecurityService.validate_readonly_sql(sql) is True


class TestApiDifferential:
    """Differential tests: AST-generated results vs handwritten parameterized SQL."""

    def test_simple_select_equals_handwritten(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'first_name'},
                {'tableId': 't1', 'columnName': 'country'},
            ],
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT id, first_name, country FROM customer ORDER BY id ASC'
        )
        _assert_results_equal(ast_rows, hand_rows, 'simple select')

    def test_inner_join_differential(self, db_connection):
        ast_query = {
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
                {'tableId': 't1', 'columnName': 'first_name'},
                {'tableId': 't1', 'columnName': 'country'},
                {'tableId': 't2', 'columnName': 'total_amount'},
            ],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT c.first_name, c.country, o.total_amount '
            'FROM customer c INNER JOIN "order" o ON c.id = o.customer_id'
        )
        _assert_results_equal(ast_rows, hand_rows, 'inner join')

    def test_three_table_join_differential(self, db_connection):
        ast_query = {
            'tables': [
                {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
                {'id': 't2', 'tableName': 'order', 'alias': 'o'},
                {'id': 't3', 'tableName': 'order_item', 'alias': 'oi'},
            ],
            'joins': [
                {'id': 'j1', 'type': 'INNER',
                 'leftTableId': 't1', 'leftColumn': 'id',
                 'rightTableId': 't2', 'rightColumn': 'customer_id',
                 'leftTable': 'customer', 'rightTable': 'order'},
                {'id': 'j2', 'type': 'INNER',
                 'leftTableId': 't2', 'leftColumn': 'id',
                 'rightTableId': 't3', 'rightColumn': 'order_id',
                 'leftTable': 'order', 'rightTable': 'order_item'},
            ],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'first_name'},
                {'tableId': 't2', 'columnName': 'id'},
                {'tableId': 't3', 'columnName': 'quantity'},
                {'tableId': 't3', 'columnName': 'unit_price'},
            ],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT c.first_name, o.id, oi.quantity, oi.unit_price '
            'FROM customer c '
            'INNER JOIN "order" o ON c.id = o.customer_id '
            'INNER JOIN order_item oi ON o.id = oi.order_id'
        )
        _assert_results_equal(ast_rows, hand_rows, 'three table join')

    def test_left_join_differential(self, db_connection):
        ast_query = {
            'tables': [
                {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
                {'id': 't2', 'tableName': 'order', 'alias': 'o'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'LEFT',
                'leftTableId': 't1', 'leftColumn': 'id',
                'rightTableId': 't2', 'rightColumn': 'customer_id',
                'leftTable': 'customer', 'rightTable': 'order',
            }],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't2', 'columnName': 'id'},
            ],
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [
                {'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'},
                {'tableId': 't2', 'columnName': 'id', 'direction': 'ASC'},
            ],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT c.id, o.id FROM customer c '
            'LEFT JOIN "order" o ON c.id = o.customer_id '
            'ORDER BY c.id ASC, o.id ASC'
        )
        _assert_results_equal(ast_rows, hand_rows, 'left join')

    def test_self_join_differential(self, db_connection):
        ast_query = {
            'tables': [
                {'id': 't1', 'tableName': 'employee', 'alias': 'e1'},
                {'id': 't2', 'tableName': 'employee', 'alias': 'e2'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'INNER',
                'leftTableId': 't1', 'leftColumn': 'department',
                'rightTableId': 't2', 'rightColumn': 'department',
                'leftTable': 'employee', 'rightTable': 'employee',
            }],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'first_name', 'alias': 'name1'},
                {'tableId': 't2', 'columnName': 'first_name', 'alias': 'name2'},
                {'tableId': 't1', 'columnName': 'department'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'id', 'cmp': '<', 'value': 100},
                ],
            },
            'having': None, 'aggregations': [],
            'orderBy': [
                {'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'},
                {'tableId': 't2', 'columnName': 'id', 'direction': 'ASC'},
            ],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT e1.first_name AS name1, e2.first_name AS name2, e1.department '
            'FROM employee e1 INNER JOIN employee e2 ON e1.department = e2.department '
            'WHERE e1.id < 100 '
            'ORDER BY e1.id ASC, e2.id ASC'
        )
        _assert_results_equal(ast_rows, hand_rows, 'self join')

    def test_where_with_nested_or_differential(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'country'},
                {'tableId': 't1', 'columnName': 'city'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN',
                     'value': ['US', 'UK']},
                    {'id': 'g1', 'op': 'OR', 'children': [
                        {'id': 'c2', 'tableId': 't1', 'columnName': 'city', 'cmp': '=', 'value': 'New York'},
                        {'id': 'c3', 'tableId': 't1', 'columnName': 'city', 'cmp': '=', 'value': 'London'},
                    ]},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT id, country, city FROM customer '
            "WHERE country IN ('US', 'UK') AND (city = 'New York' OR city = 'London')"
        )
        _assert_results_equal(ast_rows, hand_rows, 'nested AND/OR')

    def test_null_is_null_differential(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'employee', 'alias': 'e'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'first_name'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'hire_date', 'cmp': 'IS NOT NULL'},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT id, first_name FROM employee WHERE hire_date IS NOT NULL'
        )
        _assert_results_equal(ast_rows, hand_rows, 'IS NOT NULL')

    def test_aggregation_group_by_differential(self, db_connection):
        ast_query = {
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
            'selectedFields': [{'tableId': 't1', 'columnName': 'country'}],
            'where': None, 'having': None,
            'aggregations': [
                {'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM', 'alias': 'total_spent'},
                {'tableId': 't2', 'columnName': 'id', 'function': 'COUNT', 'alias': 'order_count'},
            ],
            'orderBy': [{'tableId': 't1', 'columnName': 'country', 'direction': 'ASC'}],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT c.country, SUM(o.total_amount) AS total_spent, COUNT(o.id) AS order_count '
            'FROM customer c INNER JOIN "order" o ON c.id = o.customer_id '
            'GROUP BY c.country ORDER BY c.country ASC'
        )
        _assert_results_equal(ast_rows, hand_rows, 'aggregation GROUP BY')

    def test_having_differential(self, db_connection):
        ast_query = {
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
            'selectedFields': [{'tableId': 't1', 'columnName': 'country'}],
            'where': None,
            'having': {
                'id': 'h1', 'op': 'AND', 'children': [
                    {'id': 'hc1', 'tableId': 't2', 'columnName': 'total_amount', 'cmp': '>', 'value': 100},
                ],
            },
            'aggregations': [
                {'tableId': 't2', 'columnName': 'id', 'function': 'COUNT', 'alias': 'cnt'},
            ],
            'orderBy': [{'tableId': 't1', 'columnName': 'country', 'direction': 'ASC'}],
            'limit': 1000,
        }
        ast_rows, ast_sql, ast_params = _run_ast(db_connection, ast_query)
        assert 'HAVING' in ast_sql
        hand_rows = _run_handwritten(db_connection,
            'SELECT c.country, COUNT(o.id) AS cnt '
            'FROM customer c INNER JOIN "order" o ON c.id = o.customer_id '
            'GROUP BY c.country HAVING o.total_amount > 100 '
            'ORDER BY c.country ASC'
        )
        _assert_results_equal(ast_rows, hand_rows, 'HAVING')

    def test_pagination_limited_offset_differential(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'first_name'},
            ],
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
            'limit': 3,
            'offset': 2,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT id, first_name FROM customer ORDER BY id ASC LIMIT 3 OFFSET 2'
        )
        _assert_results_equal(ast_rows, hand_rows, 'pagination')

    def test_date_filter_differential(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'order', 'alias': 'o'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'order_date'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'order_date', 'cmp': '>=', 'value': '2025-03-01'},
                ],
            },
            'having': None, 'aggregations': [],
            'orderBy': [{'tableId': 't1', 'columnName': 'order_date', 'direction': 'ASC'}],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            "SELECT id, order_date FROM \"order\" WHERE order_date >= '2025-03-01' ORDER BY order_date ASC"
        )
        _assert_results_equal(ast_rows, hand_rows, 'date filter')

    def test_cross_join_differential(self, db_connection):
        ast_query = {
            'tables': [
                {'id': 't1', 'tableName': 'category', 'alias': 'ca'},
                {'id': 't2', 'tableName': 'supplier', 'alias': 'su'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'CROSS',
                'leftTableId': 't1', 'leftColumn': '',
                'rightTableId': 't2', 'rightColumn': '',
                'leftTable': 'category', 'rightTable': 'supplier',
            }],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't2', 'columnName': 'id'},
            ],
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [
                {'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'},
                {'tableId': 't2', 'columnName': 'id', 'direction': 'ASC'},
            ],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT ca.id, su.id FROM category ca CROSS JOIN supplier su '
            'ORDER BY ca.id ASC, su.id ASC'
        )
        _assert_results_equal(ast_rows, hand_rows, 'cross join')

    def test_not_condition_differential(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'country'},
            ],
            'where': {
                'id': 'w1', 'op': 'NOT', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                ],
            },
            'having': None, 'aggregations': [],
            'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            "SELECT id, country FROM customer WHERE NOT (country = 'US') ORDER BY id ASC"
        )
        _assert_results_equal(ast_rows, hand_rows, 'NOT condition')

    def test_like_differential(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'product', 'alias': 'p'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'name'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'name', 'cmp': 'LIKE', 'value': '%Pro%'},
                ],
            },
            'having': None, 'aggregations': [],
            'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            "SELECT id, name FROM product WHERE name LIKE '%Pro%' ORDER BY id ASC"
        )
        _assert_results_equal(ast_rows, hand_rows, 'LIKE')

    def test_empty_in_returns_no_rows(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN', 'value': []},
                ],
            },
            'having': None, 'aggregations': [], 'orderBy': [], 'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        assert len(ast_rows) == 0

    def test_empty_not_in_returns_all_rows(self, db_connection):
        ast_query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'NOT IN', 'value': []},
                ],
            },
            'having': None, 'aggregations': [],
            'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
            'limit': 1000,
        }
        ast_rows, _, _ = _run_ast(db_connection, ast_query)
        hand_rows = _run_handwritten(db_connection,
            'SELECT id FROM customer ORDER BY id ASC'
        )
        _assert_results_equal(ast_rows, hand_rows, 'empty NOT IN')


class TestSaveRestore:
    def test_ast_round_trip_stable_ids(self):
        query = {
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
                {'tableId': 't1', 'columnName': 'first_name'},
                {'tableId': 't2', 'columnName': 'total_amount'},
            ],
            'where': {
                'id': 'w1', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                ],
            },
            'having': None,
            'aggregations': [],
            'orderBy': [],
            'limit': 50,
            'offset': 10,
        }
        import json
        serialized = json.dumps(query)
        restored = json.loads(serialized)

        gen1 = SQLGenerator(query)
        sql1 = gen1.generate()
        params1 = gen1.get_params()

        gen2 = SQLGenerator(restored)
        sql2 = gen2.generate()
        params2 = gen2.get_params()

        assert sql1 == sql2
        assert params1 == params2

    def test_join_order_does_not_change_semantics(self, db_connection):
        base_tables = [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'order', 'alias': 'o'},
            {'id': 't3', 'tableName': 'order_item', 'alias': 'oi'},
        ]
        base_fields = [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't3', 'columnName': 'quantity'},
        ]
        joins_v1 = [
            {'id': 'j1', 'type': 'INNER',
             'leftTableId': 't1', 'leftColumn': 'id',
             'rightTableId': 't2', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
            {'id': 'j2', 'type': 'INNER',
             'leftTableId': 't2', 'leftColumn': 'id',
             'rightTableId': 't3', 'rightColumn': 'order_id',
             'leftTable': 'order', 'rightTable': 'order_item'},
        ]
        import copy
        q1 = {
            'tables': copy.deepcopy(base_tables),
            'joins': copy.deepcopy(joins_v1),
            'selectedFields': copy.deepcopy(base_fields),
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [], 'limit': 1000,
        }
        q2 = {
            'tables': list(reversed(copy.deepcopy(base_tables))),
            'joins': list(reversed(copy.deepcopy(joins_v1))),
            'selectedFields': copy.deepcopy(base_fields),
            'where': None, 'having': None, 'aggregations': [],
            'orderBy': [], 'limit': 1000,
        }
        rows1, _, _ = _run_ast(db_connection, q1)
        rows2, _, _ = _run_ast(db_connection, q2)
        _assert_results_equal(rows1, rows2, 'join order invariance')


class TestFlaskApiSmoke:
    def test_metadata_endpoint(self, client):
        resp = client.get('/api/metadata')
        assert resp.status_code == 200
        data = resp.get_json()
        table_names = [t['name'] for t in data]
        assert 'customer' in table_names
        assert 'order' in table_names

    def test_generate_sql_endpoint(self, client):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 10,
        }
        resp = client.post('/api/generate-sql', json=query)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'sql' in data
        assert 'params' in data

    def test_execute_query_endpoint(self, client):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't1', 'columnName': 'first_name'},
            ],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 5,
        }
        resp = client.post('/api/execute-query', json=query)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'columns' in data
        assert 'rows' in data
        assert 'rowCount' in data
        assert data['rowCount'] <= 5

    def test_explain_endpoint(self, client):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 10,
        }
        resp = client.post('/api/explain', json=query)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'queryPlan' in data
        assert 'bytecode' in data
        assert 'sql' in data

    def test_explain_uses_same_ast(self, client):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
            'where': None, 'having': None, 'aggregations': [], 'orderBy': [],
            'limit': 10,
        }
        gen_resp = client.post('/api/generate-sql', json=query)
        gen_data = gen_resp.get_json()
        explain_resp = client.post('/api/explain', json=query)
        explain_data = explain_resp.get_json()
        assert gen_data['sql'] == explain_data['sql']

    def test_rejected_join_returns_400(self, client):
        query = {
            'tables': [
                {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
                {'id': 't2', 'tableName': 'order', 'alias': 'o'},
            ],
            'joins': [{
                'id': 'j1', 'type': 'FULL',
                'leftTableId': 't1', 'leftColumn': 'id',
                'rightTableId': 't2', 'rightColumn': 'customer_id',
                'leftTable': 'customer', 'rightTable': 'order',
            }],
            'selectedFields': [], 'where': None, 'having': None,
            'aggregations': [], 'orderBy': [], 'limit': 100,
        }
        resp = client.post('/api/generate-sql', json=query)
        assert resp.status_code == 400
        assert 'FULL JOIN' in resp.get_json()['error']
