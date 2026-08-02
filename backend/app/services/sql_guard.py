"""Static and runtime guards that keep query execution single, read-only and
bounded. The visual builder is the only intended producer of SQL, but the
execution layer treats every incoming statement as untrusted and enforces:

  * exactly one statement (no multi-statement piggybacking),
  * no SQL comments (block ``--`` / ``/* */`` bypass tricks),
  * read-only shape (must start with SELECT or WITH ... SELECT),
  * no DDL/DML keywords, even hidden inside a CTE body,
  * no dangerous PRAGMA / ATTACH / VACUUM / etc.,
  * a SQLite authorizer that denies any non-read action at prepare time.
"""
import re
import sqlite3

# Keywords that must never appear in a read-only query (checked after string
# literals and quoted identifiers are stripped out).
FORBIDDEN_KEYWORDS = {
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'REPLACE',
    'TRUNCATE', 'ATTACH', 'DETACH', 'PRAGMA', 'VACUUM', 'REINDEX',
    'ANALYZE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE', 'INTO', 'RETURNING',
    'UPSERT', 'BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT', 'RELEASE',
}

_QUOTED_DOUBLE = re.compile(r'"(?:[^"]|"")*"')
_QUOTED_SINGLE = re.compile(r"'(?:[^']|'')*'")
_WORD = re.compile(r'[A-Za-z_]+')
_EXPLAIN_PREFIX = re.compile(r'^\s*EXPLAIN(\s+QUERY\s+PLAN)?\s+', re.IGNORECASE)


class UnsafeQueryError(ValueError):
    """Raised when a statement fails the read-only safety checks."""


def _strip_literals_and_identifiers(sql):
    """Remove double-quoted identifiers and single-quoted string literals so
    keyword scanning cannot be fooled by a column named ``delete`` or a value
    containing ``DROP TABLE``."""
    sql = _QUOTED_DOUBLE.sub(' ', sql)
    sql = _QUOTED_SINGLE.sub(' ', sql)
    return sql


def validate_read_only_sql(sql):
    if not sql or not sql.strip():
        raise UnsafeQueryError('Empty query')

    # Comment bypass: reject any SQL comment markers outright.
    if '--' in sql or '/*' in sql or '*/' in sql:
        raise UnsafeQueryError('SQL comments are not allowed')

    # An EXPLAIN / EXPLAIN QUERY PLAN wrapper is read-only; validate the body.
    body = _EXPLAIN_PREFIX.sub('', sql, count=1)

    scrubbed = _strip_literals_and_identifiers(body)

    # Multi-statement: only a single optional trailing semicolon is permitted.
    without_trailing = scrubbed.rstrip().rstrip(';')
    if ';' in without_trailing:
        raise UnsafeQueryError('Multiple statements are not allowed')

    stripped = scrubbed.lstrip()
    head = stripped[:6].upper()
    if not (head.startswith('SELECT') or head.startswith('WITH')):
        raise UnsafeQueryError('Only read-only SELECT queries are allowed')

    words = {w.upper() for w in _WORD.findall(scrubbed)}
    bad = words & FORBIDDEN_KEYWORDS
    if bad:
        raise UnsafeQueryError(
            f'Disallowed keyword(s) in query: {", ".join(sorted(bad))}'
        )
    return True


# --- SQLite authorizer: last line of defence at statement-prepare time ---
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, 'SQLITE_RECURSIVE', 33),
    getattr(sqlite3, 'SQLITE_TRANSACTION', 22),
}


def read_only_authorizer(action, arg1, arg2, db_name, trigger):
    if action in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    # Explicitly deny everything else (writes, PRAGMA, ATTACH, etc.).
    return sqlite3.SQLITE_DENY
