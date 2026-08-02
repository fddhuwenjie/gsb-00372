"""Runtime execution safety: read-only enforcement, row-limit truncation,
cancellation, and that dangerous statements never reach the database.

These use the isolated temp SQLite database created by the test fixtures.
"""
import threading
import pytest

from app.services.query_executor import (
    QueryExecutor, QueryCancelledError, DEFAULT_MAX_ROWS,
)
from app.services.sql_guard import UnsafeQueryError


def simple_query(limit=100):
    return {
        'tables': [{'id': 'p', 'tableName': 'product', 'alias': 'p', 'position': {}}],
        'joins': [], 'selectedFields': [{'tableId': 'p', 'columnName': 'id'}],
        'where': None, 'aggregations': [], 'limit': limit,
    }


def test_execute_is_read_only_authorizer(app):
    # A hand-crafted write must be denied by the authorizer, even if it somehow
    # reached the connection.
    with app.app_context():
        with pytest.raises((UnsafeQueryError, Exception)):
            QueryExecutor._run_readonly(
                'DELETE FROM product', {}, 1000, 10, None
            )


def test_row_limit_truncates(app):
    # max_rows caps returned rows and flags truncation, independent of LIMIT.
    with app.app_context():
        run = QueryExecutor._run_readonly(
            'SELECT id FROM product', {}, 2000, 3, None
        )
    assert len(run['rows']) == 3
    assert run['truncated'] is True


def test_cancel_event_aborts(app):
    cancel = threading.Event()
    cancel.set()  # already cancelled before running
    with app.app_context():
        with pytest.raises(QueryCancelledError):
            # A cross join large enough that the progress handler fires.
            QueryExecutor._run_readonly(
                'SELECT a.id FROM product a, product b, product c',
                {}, 5000, DEFAULT_MAX_ROWS, cancel,
            )


def test_execute_returns_truncated_flag(app):
    with app.app_context():
        res = QueryExecutor.execute(simple_query(limit=1000), max_rows=2)
    assert res['truncated'] is True
    assert res['rowCount'] == 2
