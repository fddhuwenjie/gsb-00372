"""Unit tests for the SQL generator's AST compilation."""
import pytest

from app.services.sql_generator import SQLGenerator
from app.services.security_service import SecurityService


def compile_(qs):
    gen = SQLGenerator(qs)
    return gen.generate(), gen.get_params()


def base_qs(**overrides):
    qs = {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [
            {
                'id': 'j1',
                'type': 'INNER',
                'leftTableId': 't1',
                'leftColumn': 'id',
                'rightTableId': 't2',
                'rightColumn': 'customer_id',
                'leftTable': 'customer',
                'rightTable': 'order',
            }
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't2', 'columnName': 'total_amount'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 100,
    }
    qs.update(overrides)
    return qs


def test_inner_join_basic():
    sql, params = compile_(base_qs())
    assert 'INNER JOIN' in sql
    assert '"c"."id" = "o"."customer_id"' in sql
    assert params  # limit is bound


def test_left_join():
    qs = base_qs()
    qs['joins'][0]['type'] = 'LEFT'
    sql, _ = compile_(qs)
    assert 'LEFT JOIN' in sql


def test_cross_join_has_no_on_clause():
    qs = base_qs()
    qs['joins'][0]['type'] = 'CROSS'
    qs['joins'][0].pop('leftColumn')
    qs['joins'][0].pop('rightColumn')
    sql, _ = compile_(qs)
    assert 'CROSS JOIN' in sql
    assert 'ON' not in sql


@pytest.mark.parametrize('bad_type', ['RIGHT', 'FULL', 'RIGHT OUTER', 'FULL OUTER'])
def test_right_and_full_join_rejected(bad_type):
    qs = base_qs()
    qs['joins'][0]['type'] = bad_type
    with pytest.raises(ValueError, match='not supported by SQLite'):
        compile_(qs)


def test_limit_is_parameter_bound():
    sql, params = compile_(base_qs(limit=25))
    assert 'LIMIT :' in sql
    assert 25 in params.values()
    assert 'LIMIT 25' not in sql


def test_offset_is_parameter_bound():
    sql, params = compile_(base_qs(limit=10, offset=20))
    assert 'OFFSET :' in sql
    assert 20 in params.values()


def test_nested_and_or_conditions():
    qs = base_qs()
    qs['where'] = {
        'op': 'AND',
        'children': [
            {'tableId': 't2', 'columnName': 'total_amount', 'cmp': '>', 'value': 100},
            {
                'op': 'OR',
                'children': [
                    {'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                    {'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'UK'},
                ],
            },
        ],
    }
    sql, params = compile_(qs)
    assert 'WHERE' in sql
    assert 'AND' in sql
    assert 'OR' in sql
    assert params['p1'] == 100
    assert params['p2'] == 'US'
    assert params['p3'] == 'UK'


def test_not_condition():
    qs = base_qs()
    qs['where'] = {
        'op': 'NOT',
        'child': {'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
    }
    sql, _ = compile_(qs)
    assert 'NOT (' in sql


def test_is_null_and_is_not_null():
    for op in ('IS NULL', 'IS NOT NULL'):
        qs = base_qs()
        qs['where'] = {'tableId': 't2', 'columnName': 'total_amount', 'cmp': op}
        sql, params = compile_(qs)
        assert op in sql
        # no value bound for IS NULL
        assert all(v is not None for v in params.values())


def test_null_equality_normalises_to_is_null():
    qs = base_qs()
    qs['where'] = {'tableId': 't1', 'columnName': 'email', 'cmp': '=', 'value': None}
    sql, _ = compile_(qs)
    assert 'IS NULL' in sql


def test_empty_in_renders_false_constant():
    qs = base_qs()
    qs['where'] = {'tableId': 't1', 'columnName': 'country', 'cmp': 'IN', 'value': []}
    sql, params = compile_(qs)
    assert '0 = 1' in sql
    # no IN (...) value list placeholder should be emitted
    assert 'IN (' not in sql
    # no user params beyond the LIMIT
    assert all(v == qs['limit'] for v in params.values())


def test_empty_not_in_renders_true_constant():
    qs = base_qs()
    qs['where'] = {
        'tableId': 't1', 'columnName': 'country', 'cmp': 'NOT IN', 'value': []
    }
    sql, _ = compile_(qs)
    assert '1 = 1' in sql


def test_in_with_values_bound():
    qs = base_qs()
    qs['where'] = {
        'tableId': 't1', 'columnName': 'country', 'cmp': 'IN',
        'value': ['US', 'UK', 'DE'],
    }
    sql, params = compile_(qs)
    assert 'IN (' in sql
    assert list(params.values())[:3] == ['US', 'UK', 'DE']


def test_self_join_uses_distinct_aliases():
    qs = {
        'tables': [
            {'id': 'e1', 'tableName': 'employee', 'alias': 'mgr'},
            {'id': 'e2', 'tableName': 'employee', 'alias': 'emp'},
        ],
        'joins': [{
            'id': 'j1', 'type': 'LEFT',
            'leftTableId': 'e1', 'leftColumn': 'id',
            'rightTableId': 'e2', 'rightColumn': 'id',
            'leftTable': 'employee', 'rightTable': 'employee',
        }],
        'selectedFields': [
            {'tableId': 'e1', 'columnName': 'last_name', 'alias': 'manager'},
            {'tableId': 'e2', 'columnName': 'last_name', 'alias': 'worker'},
        ],
        'where': None,
        'aggregations': [],
        'limit': 10,
    }
    sql, params = compile_(qs)
    assert '"mgr"' in sql
    assert '"emp"' in sql
    # Both duplicate columns must be qualified by their distinct aliases.
    assert '"mgr"."last_name"' in sql
    assert '"emp"."last_name"' in sql


def test_three_table_join():
    qs = base_qs()
    qs['tables'].append({'id': 't3', 'tableName': 'order_item', 'alias': 'oi'})
    qs['joins'].append({
        'id': 'j2', 'type': 'INNER',
        'leftTableId': 't2', 'leftColumn': 'id',
        'rightTableId': 't3', 'rightColumn': 'order_id',
        'leftTable': 'order', 'rightTable': 'order_item',
    })
    qs['selectedFields'].append({'tableId': 't3', 'columnName': 'quantity'})
    sql, _ = compile_(qs)
    assert 'INNER JOIN "order_item"' in sql
    assert '"o"."id" = "oi"."order_id"' in sql


def test_aggregation_and_group_by():
    qs = base_qs()
    qs['selectedFields'] = [{'tableId': 't1', 'columnName': 'country'}]
    qs['aggregations'] = [
        {'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM',
         'alias': 'total_spent'},
    ]
    sql, _ = compile_(qs)
    assert 'SUM(' in sql
    assert 'GROUP BY' in sql
    assert '"total_spent"' in sql


def test_having_clause():
    qs = base_qs()
    qs['selectedFields'] = [{'tableId': 't1', 'columnName': 'country'}]
    qs['aggregations'] = [
        {'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM',
         'alias': 'total_spent'},
    ]
    qs['having'] = {
        'tableId': 't2', 'columnName': 'total_amount', 'cmp': '>',
        'value': 1000, 'function': 'SUM',
    }
    sql, params = compile_(qs)
    assert 'HAVING' in sql
    assert 1000 in params.values()


def test_order_by():
    qs = base_qs()
    qs['orderBy'] = [
        {'tableId': 't2', 'columnName': 'total_amount', 'direction': 'DESC'},
    ]
    sql, _ = compile_(qs)
    assert 'ORDER BY' in sql
    assert 'DESC' in sql


def test_duplicate_alias_rejected():
    qs = base_qs()
    qs['tables'][1]['alias'] = 'c'  # same as first table
    with pytest.raises(ValueError, match='[Dd]uplicate'):
        compile_(qs)


def test_unknown_table_reference_rejected():
    qs = base_qs()
    qs['selectedFields'][0]['tableId'] = 'ghost'
    with pytest.raises(ValueError):
        compile_(qs)


def test_column_names_are_quoted():
    qs = base_qs()
    sql, _ = compile_(qs)
    assert '"first_name"' in sql
    # ensure no unqualified interpolation
    assert ' first_name ' not in sql


def test_params_separated_from_sql():
    qs = base_qs()
    qs['where'] = {
        'tableId': 't1', 'columnName': 'country', 'cmp': '=',
        'value': "US'; DROP TABLE customer;--",
    }
    sql, params = compile_(qs)
    assert 'DROP' not in sql.upper()
    assert '--' not in sql
    # the malicious value only exists as a bound parameter
    assert any('DROP' in str(v) for v in params.values())
