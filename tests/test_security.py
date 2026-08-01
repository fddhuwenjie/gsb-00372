"""Execution-safety tests: single read-only statements only, comment and
multi-statement bypasses, write CTEs, dangerous PRAGMA, plus timeout,
cancellation and row-cap enforcement.
"""
import threading
import time

import pytest

from app.database import db
from app.services.query_executor import (
    QueryExecutor, QueryCancelled, QueryTimeout,
)
from app.services.security_service import SecurityService


class TestReadOnlyValidation:
    @pytest.mark.parametrize('sql', [
        'SELECT id FROM customer WHERE country = :p1',
        'SELECT * FROM "order" LIMIT :p1',
        'WITH x AS (SELECT id FROM customer) SELECT * FROM x',
        'SELECT "delete" FROM t',          # quoted identifier named like a keyword
        'SELECT * FROM t;',                # single trailing semicolon tolerated
    ])
    def test_allowed_statements(self, sql):
        assert SecurityService.validate_read_only_sql(sql) == sql

    @pytest.mark.parametrize('sql', [
        # write statements
        'INSERT INTO customer (id) VALUES (1)',
        'UPDATE customer SET country = \'X\'',
        'DELETE FROM customer',
        'DROP TABLE customer',
        'ALTER TABLE customer ADD COLUMN x INT',
        'CREATE TABLE evil (id INT)',
        'REPLACE INTO customer (id) VALUES (1)',
        'VACUUM',
        'ATTACH DATABASE \'/tmp/x.db\' AS x',
        # dangerous PRAGMA
        'PRAGMA writable_schema = ON',
        'PRAGMA journal_mode = OFF',
        # data-modifying CTE (SQLite write CTE)
        'WITH x AS (DELETE FROM customer RETURNING *) SELECT * FROM x',
        'WITH x AS (UPDATE customer SET country = \'X\' RETURNING id) SELECT * FROM x',
        'WITH x AS (INSERT INTO customer (id) VALUES (1) RETURNING id) SELECT * FROM x',
        # multi-statement
        'SELECT 1; SELECT 2',
        'SELECT 1; DROP TABLE customer;',
        # comment bypass attempts
        'SELECT 1 -- comment',
        'SELECT 1 /* comment */',
        'SEL/**/ECT 1',
        # transaction control
        'BEGIN TRANSACTION',
        'SELECT * FROM customer; COMMIT;',
    ])
    def test_rejected_statements(self, sql):
        with pytest.raises(ValueError):
            SecurityService.validate_read_only_sql(sql)


def simple_query(limit=100):
    return {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
        'where': None,
        'having': None,
        'aggregations': [],
        'limit': limit,
    }


class TestExecutionLimits:
    def test_row_cap_truncates_and_flags(self, app):
        app.config['MAX_ROWS'] = 5
        try:
            with app.app_context():
                result = QueryExecutor.execute(simple_query(limit=100))
            assert result['rowCount'] == 5
            assert len(result['rows']) == 5
            assert result['truncated'] is True
        finally:
            app.config['MAX_ROWS'] = 1000

    def test_timeout_interrupts_query(self, app):
        app.config['QUERY_TIMEOUT_MS'] = 0  # interrupt at the first progress tick
        try:
            with app.app_context():
                with pytest.raises(QueryTimeout):
                    QueryExecutor.execute(simple_query())
        finally:
            app.config['QUERY_TIMEOUT_MS'] = 5000

    def test_cancel_before_execute_aborts(self, app):
        session = 'cancel-test-session'
        with app.app_context():
            QueryExecutor.request_cancel(session)
            with pytest.raises(QueryCancelled):
                QueryExecutor.execute(simple_query(), user_session=session)

    def test_cancel_during_execute_aborts(self, app):
        session = 'cancel-mid-session'
        # 5-way cross product (~39^5 rows) with COUNT: full scan that cannot
        # finish before the cancellation lands.
        heavy = {
            'tables': [
                {'id': 'a', 'tableName': 'order_item', 'alias': 'a'},
                {'id': 'b', 'tableName': 'order_item', 'alias': 'b'},
                {'id': 'c', 'tableName': 'order_item', 'alias': 'c'},
                {'id': 'd', 'tableName': 'order_item', 'alias': 'd'},
                {'id': 'e', 'tableName': 'order_item', 'alias': 'e'},
            ],
            'joins': [
                {'id': 'j1', 'type': 'CROSS', 'leftTableId': 'a', 'rightTableId': 'b',
                 'leftTable': 'order_item', 'rightTable': 'order_item'},
                {'id': 'j2', 'type': 'CROSS', 'leftTableId': 'b', 'rightTableId': 'c',
                 'leftTable': 'order_item', 'rightTable': 'order_item'},
                {'id': 'j3', 'type': 'CROSS', 'leftTableId': 'c', 'rightTableId': 'd',
                 'leftTable': 'order_item', 'rightTable': 'order_item'},
                {'id': 'j4', 'type': 'CROSS', 'leftTableId': 'd', 'rightTableId': 'e',
                 'leftTable': 'order_item', 'rightTable': 'order_item'},
            ],
            'selectedFields': [{'tableId': 'a', 'columnName': 'id'}],
            'where': None,
            # COUNT forces a full scan of the cross product, so the query
            # cannot finish early via LIMIT and the progress handler fires.
            'aggregations': [{'tableId': 'a', 'columnName': 'id', 'function': 'COUNT'}],
            'limit': 1000,
        }
        outcome = {}

        def run():
            with app.app_context():
                try:
                    QueryExecutor.execute(heavy, user_session=session)
                    outcome['result'] = 'completed'
                except QueryCancelled:
                    outcome['result'] = 'cancelled'
                except Exception as e:  # noqa: BLE001
                    outcome['result'] = f'error: {e}'

        worker = threading.Thread(target=run)
        worker.start()
        time.sleep(0.05)
        QueryExecutor.request_cancel(session)
        worker.join(timeout=30)
        assert outcome.get('result') == 'cancelled'

    def test_executor_rejects_unsafe_generated_sql(self, app, monkeypatch):
        # Even if the generator were compromised, the executor re-validates.
        monkeypatch.setattr(
            QueryExecutor, 'generate_sql',
            staticmethod(lambda qs: {'sql': 'SELECT 1; DROP TABLE customer', 'params': {}}),
        )
        with app.app_context():
            with pytest.raises(ValueError, match='Multiple SQL statements'):
                QueryExecutor.execute(simple_query())

    def test_executed_sql_passes_read_only_validation(self, app):
        with app.app_context():
            result = QueryExecutor.execute({
                'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
                'joins': [],
                'selectedFields': [{'tableId': 't1', 'columnName': 'country'}],
                'where': {'id': 'w', 'op': 'AND', 'children': [
                    {'id': 'c1', 'tableId': 't1', 'columnName': 'country',
                     'cmp': '=', 'value': "US'; DROP TABLE customer; --"},
                ]},
                'aggregations': [],
                'limit': 10,
            })
        # injection string travelled purely as a bound parameter
        assert result['params'] == {'p1': "US'; DROP TABLE customer; --", 'p2': 10}
        assert result['rowCount'] == 0
        SecurityService.validate_read_only_sql(result['sql'])

    def test_explain_uses_same_ast_and_params_as_execute(self, app):
        query = {
            'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
            'joins': [],
            'selectedFields': [{'tableId': 't1', 'columnName': 'country'}],
            'where': {'id': 'w', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
            ]},
            'aggregations': [],
            'limit': 10,
        }
        with app.app_context():
            executed = QueryExecutor.execute(query)
            explained = QueryExecutor.explain(query)
        assert explained['sql'] == executed['sql']
        assert explained['params'] == executed['params']
        assert explained['queryPlan']['nodes']
