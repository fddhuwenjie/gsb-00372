"""Shared helpers for the test suite."""
from sqlalchemy import text


def run_reference(connection, sql, params=None):
    """Run hand-written parameterized reference SQL and return
    (column_names, rows)."""
    result = connection.execute(text(sql), params or {})
    columns = list(result.keys())
    rows = [list(row) for row in result.fetchall()]
    return columns, rows
