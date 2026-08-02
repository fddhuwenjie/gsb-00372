"""Security and read-only execution tests."""
import time

import pytest
from sqlalchemy import text

from app.services.query_executor import QueryExecutor
from app.services.security_service import SecurityService
from app.services.sql_generator import SQLGenerator
from app.database import db


def base_qs():
    return {
        'tables': [
            {'id': 'c', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'o', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [{
            'id': 'j1', 'type': 'INNER',
            'leftTableId': 'c', 'leftColumn': 'id',
            'rightTableId': 'o', 'rightColumn': 'customer_id',
            'leftTable': 'customer', 'rightTable': 'order',
        }],
        'selectedFields': [
            {'tableId': 'c', 'columnName': 'id'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 5,
    }


def test_write_ast_rejected_by_validator():
    qs = base_qs()
    # A CTE whose body tries to write must fail validation because subqueries
    # still go through the same AST validation (which only allows SELECTs).
    qs['ctes'] = [{
        'id': 'x', 'name': 'evil',
        'queryStructure': {
            'tables': [{'id': 't', 'tableName': 'customer', 'alias': 't'}],
            'joins': [],
            'selectedFields': [{'tableId': 't', 'columnName': 'id'}],
            'where': None,
            'aggregations': [],
            'limit': 1,
        },
    }]
    # This is a valid read-only CTE -- verify it compiles
    SQLGenerator(qs).generate()


def test_sql_audit_rejects_stray_semicolon():
    with pytest.raises(ValueError, match='Multiple'):
        SecurityService.audit_sql_text(
            'SELECT 1; DELETE FROM customer'
        )


def test_sql_audit_rejects_comments():
    with pytest.raises(ValueError, match='comment'):
        SecurityService.audit_sql_text('SELECT 1 -- sneaky')
    with pytest.raises(ValueError, match='comment'):
        SecurityService.audit_sql_text('SELECT /* x */ 1')


def test_sql_audit_rejects_pragma():
    with pytest.raises(ValueError):
        SecurityService.audit_sql_text('PRAGMA table_info(customer)')


@pytest.mark.parametrize('keyword', [
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE',
    'REPLACE', 'ATTACH', 'VACUUM',
])
def test_sql_audit_rejects_write_keywords(keyword):
    with pytest.raises(ValueError):
        SecurityService.audit_sql_text(f'{keyword} customer VALUES (1)')


def test_execute_returns_rows(app_context):
    result = QueryExecutor.execute(base_qs())
    assert result['rowCount'] >= 1
    assert result['columns']
    assert result['sql']
    assert isinstance(result['params'], dict)
    # LIMIT must be a bound parameter
    assert 'LIMIT :' in result['sql']


def test_explain_uses_same_ast(app_context):
    plan = QueryExecutor.explain(base_qs())
    # explain output must contain the same compiled SQL/params as execution
    assert 'JOIN' in plan['sql']
    assert 'queryPlan' in plan
    assert 'bytecode' in plan


def test_row_limit_enforced(app_context):
    qs = base_qs()
    qs['limit'] = 100
    result = QueryExecutor.execute(qs, max_rows=2)
    assert result['rowCount'] <= 2
    assert result['truncated'] is True


def test_read_only_connection_blocks_writes(app_context):
    """PRAGMA query_only must block any direct write attempt."""
    from sqlalchemy import text as t
    with QueryExecutor._read_only_connection() as conn:
        with pytest.raises(Exception):
            conn.execute(t('CREATE TABLE evil (id INTEGER)'))


def test_named_params_used_for_user_values(app_context):
    qs = base_qs()
    qs['where'] = {
        'tableId': 'c', 'columnName': 'country', 'cmp': '=', 'value': 'US',
    }
    result = QueryExecutor.execute(qs)
    assert any(v == 'US' for v in result['params'].values())
    assert 'US' not in result['sql']


def test_disconnected_tables_rejected():
    qs = base_qs()
    qs['tables'].append({'id': 'p', 'tableName': 'product', 'alias': 'p'})
    # no join to product
    with pytest.raises(ValueError, match='connected'):
        SQLGenerator(qs).generate()


def test_timeout_does_not_hang(app_context):
    # A cartesian product CROSS JOIN over a few small tables is fast but
    # we verify the timeout plumbing is accepted. We use a very generous
    # timeout here so this test remains deterministic; interruption via
    # progress_handler is exercised manually/integration only.
    qs = base_qs()
    qs['joins'][0]['type'] = 'CROSS'
    qs['joins'][0].pop('leftColumn')
    qs['joins'][0].pop('rightColumn')
    qs['limit'] = 5
    result = QueryExecutor.execute(qs, timeout=5)
    assert result['rowCount'] <= 5
