"""Unit tests for the SQL generator: shape, parameter binding, and rejection
rules. These exercise the generator in isolation (no database)."""
import pytest
from app.services.sql_generator import SQLGenerator
from app.services.security_service import SecurityService


def gen(qs):
    g = SQLGenerator(qs)
    return g.generate(), g.get_params()


def base_tables(*specs):
    return [
        {'id': tid, 'tableName': name, 'alias': alias, 'position': {}}
        for tid, name, alias in specs
    ]


def test_single_table_star():
    sql, params = gen({
        'tables': base_tables(('c', 'customer', 'c')),
        'joins': [], 'selectedFields': [], 'where': None,
        'aggregations': [], 'limit': 10,
    })
    assert 'FROM "customer" "c"' in sql
    assert sql.strip().endswith('LIMIT :p1')
    assert params == {'p1': 10}


def test_limit_and_offset_are_parameters():
    sql, params = gen({
        'tables': base_tables(('c', 'customer', 'c')),
        'joins': [], 'selectedFields': [], 'where': None,
        'aggregations': [], 'limit': 5, 'offset': 20,
    })
    assert 'LIMIT :p1 OFFSET :p2' in sql
    assert params == {'p1': 5, 'p2': 20}


def test_self_join_distinct_aliases():
    sql, _ = gen({
        'tables': base_tables(('t1', 'employee', 'e1'), ('t2', 'employee', 'e2')),
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'id',
                   'rightTableId': 't2', 'rightColumn': 'id', 'leftTable': 'employee',
                   'rightTable': 'employee'}],
        'selectedFields': [{'tableId': 't1', 'columnName': 'first_name'},
                           {'tableId': 't2', 'columnName': 'first_name'}],
        'where': None, 'aggregations': [], 'limit': 10,
    })
    assert '"employee" "e1"' in sql
    assert '"employee" "e2"' in sql
    assert '"e1"."first_name"' in sql and '"e2"."first_name"' in sql


def test_empty_in_is_false_empty_not_in_is_true():
    sql_in, _ = gen({
        'tables': base_tables(('c', 'customer', 'c')), 'joins': [],
        'selectedFields': [], 'aggregations': [], 'limit': 10,
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'a', 'tableId': 'c', 'columnName': 'country', 'cmp': 'IN', 'value': []}]},
    })
    assert '(1 = 0)' in sql_in
    sql_notin, _ = gen({
        'tables': base_tables(('c', 'customer', 'c')), 'joins': [],
        'selectedFields': [], 'aggregations': [], 'limit': 10,
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'a', 'tableId': 'c', 'columnName': 'country', 'cmp': 'NOT IN', 'value': []}]},
    })
    assert '(1 = 1)' in sql_notin


def test_null_comparisons_take_no_parameter():
    sql, params = gen({
        'tables': base_tables(('o', 'order', 'o')), 'joins': [],
        'selectedFields': [], 'aggregations': [], 'limit': 10,
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'a', 'tableId': 'o', 'columnName': 'employee_id', 'cmp': 'IS NULL'}]},
    })
    assert '"o"."employee_id" IS NULL' in sql
    assert params == {'p1': 10}  # only the limit


def test_not_operator_wraps_children():
    sql, _ = gen({
        'tables': base_tables(('c', 'customer', 'c')), 'joins': [],
        'selectedFields': [], 'aggregations': [], 'limit': 10,
        'where': {'id': 'w', 'op': 'NOT', 'children': [
            {'id': 'a', 'tableId': 'c', 'columnName': 'country', 'cmp': '=', 'value': 'US'}]},
    })
    assert '(NOT ' in sql


@pytest.mark.parametrize('bad_type', ['RIGHT', 'FULL'])
def test_right_and_full_join_rejected(bad_type):
    with pytest.raises(ValueError):
        gen({
            'tables': base_tables(('a', 'category', 'ca'), ('b', 'product', 'p')),
            'joins': [{'id': 'j', 'type': bad_type, 'leftTableId': 'a', 'leftColumn': 'id',
                       'rightTableId': 'b', 'rightColumn': 'category_id',
                       'leftTable': 'category', 'rightTable': 'product'}],
            'selectedFields': [], 'where': None, 'aggregations': [], 'limit': 10,
        })


def test_invalid_identifier_rejected():
    with pytest.raises(ValueError):
        gen({
            'tables': base_tables(('c', 'customer', 'c')), 'joins': [],
            'selectedFields': [{'tableId': 'c', 'columnName': 'name; DROP TABLE x'}],
            'where': None, 'aggregations': [], 'limit': 10,
        })


def test_join_order_independent_of_authoring_order():
    """Authoring the join list in reverse must still produce valid SQL that
    attaches every table to the in-scope query."""
    tables = base_tables(('c', 'customer', 'c'), ('o', 'order', 'o'), ('e', 'employee', 'e'))
    joins = [
        {'id': 'j2', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'employee_id',
         'rightTableId': 'e', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'employee'},
        {'id': 'j1', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
         'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'},
    ]
    sql, _ = gen({'tables': tables, 'joins': joins, 'selectedFields': [],
                  'where': None, 'aggregations': [], 'limit': 10})
    assert sql.count('JOIN') == 2
