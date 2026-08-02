"""Tests for the read-only execution guard: comment bypass, multi-statement,
CTE writes, dangerous PRAGMA and DDL/DML keywords must all be rejected."""
import pytest
from app.services.sql_guard import validate_read_only_sql, UnsafeQueryError


def test_plain_select_allowed():
    assert validate_read_only_sql('SELECT * FROM customer')


def test_with_select_allowed():
    assert validate_read_only_sql('WITH x AS (SELECT 1) SELECT * FROM x')


def test_explain_allowed():
    assert validate_read_only_sql('EXPLAIN QUERY PLAN SELECT * FROM customer')
    assert validate_read_only_sql('EXPLAIN SELECT * FROM customer')


@pytest.mark.parametrize('sql', [
    'SELECT 1; DROP TABLE customer',            # multi-statement
    'SELECT 1 -- comment',                       # line comment bypass
    'SELECT 1 /* block */',                      # block comment bypass
    'DELETE FROM customer',                      # DML
    'UPDATE customer SET x = 1',                 # DML
    'INSERT INTO customer VALUES (1)',           # DML
    'DROP TABLE customer',                       # DDL
    'PRAGMA table_info(customer)',               # dangerous pragma
    'ATTACH DATABASE "x" AS y',                  # attach
    'VACUUM',                                     # vacuum
    'WITH x AS (INSERT INTO t VALUES (1)) SELECT * FROM x',  # CTE write
    'CREATE TABLE t (a int)',                    # DDL
])
def test_unsafe_statements_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate_read_only_sql(sql)


def test_keyword_inside_string_literal_is_safe():
    # 'DROP' appears only inside a quoted literal -> allowed.
    assert validate_read_only_sql("SELECT * FROM customer WHERE name = 'DROP TABLE'")


def test_column_named_like_keyword_via_quoting_is_safe():
    assert validate_read_only_sql('SELECT "delete" FROM customer')


def test_trailing_semicolon_allowed():
    assert validate_read_only_sql('SELECT * FROM customer;')
