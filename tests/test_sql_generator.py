"""Unit tests for the SQL generator: unified AST semantics, join handling,
condition trees, parameter binding and explicit rejection of unsupported SQL.
"""
import pytest

from app.services.sql_generator import SQLGenerator


def make_query(**overrides):
    query = {
        'tables': [
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'order', 'alias': 'o'},
        ],
        'joins': [
            {'id': 'j1', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'id',
             'rightTableId': 't2', 'rightColumn': 'customer_id',
             'leftTable': 'customer', 'rightTable': 'order'},
        ],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't2', 'columnName': 'total_amount'},
        ],
        'where': None,
        'having': None,
        'aggregations': [],
        'limit': 100,
    }
    query.update(overrides)
    return query


def generate(query):
    gen = SQLGenerator(query)
    return gen.generate(), gen.get_params()


class TestSelectAndAliases:
    def test_basic_inner_join(self):
        sql, params = generate(make_query())
        assert 'SELECT "c"."first_name", "o"."total_amount"' in sql
        assert 'FROM "customer" "c"' in sql
        assert 'INNER JOIN "order" "o" ON "c"."id" = "o"."customer_id"' in sql
        # pagination is always a bound parameter
        assert 'LIMIT :p1' in sql
        assert params == {'p1': 100}

    def test_duplicate_column_names_are_disambiguated(self):
        query = make_query(selectedFields=[
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't2', 'columnName': 'id'},
        ])
        sql, _ = generate(query)
        assert '"c"."id" AS "c_id"' in sql
        assert '"o"."id" AS "o_id"' in sql

    def test_duplicate_explicit_alias_rejected(self):
        query = make_query(selectedFields=[
            {'tableId': 't1', 'columnName': 'id', 'alias': 'x'},
            {'tableId': 't2', 'columnName': 'id', 'alias': 'x'},
        ])
        with pytest.raises(ValueError, match='Duplicate output column alias'):
            generate(query)

    def test_duplicate_table_alias_rejected(self):
        query = make_query(tables=[
            {'id': 't1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 't2', 'tableName': 'customer', 'alias': 'c'},
        ])
        with pytest.raises(ValueError, match='Duplicate table alias'):
            generate(query)

    def test_missing_alias_derived_deterministically(self):
        query = make_query(
            tables=[
                {'id': 't1', 'tableName': 'customer'},
                {'id': 't2', 'tableName': 'customer'},
            ],
            joins=[
                {'id': 'j1', 'type': 'INNER', 'leftTableId': 't1', 'leftColumn': 'id',
                 'rightTableId': 't2', 'rightColumn': 'id',
                 'leftTable': 'customer', 'rightTable': 'customer'},
            ],
            selectedFields=[
                {'tableId': 't1', 'columnName': 'id'},
                {'tableId': 't2', 'columnName': 'id'},
            ],
        )
        sql, _ = generate(query)
        assert 'FROM "customer" "customer"' in sql
        assert 'INNER JOIN "customer" "customer_2"' in sql
        assert '"customer"."id" AS "customer_id"' in sql
        assert '"customer_2"."id" AS "customer_2_id"' in sql

    def test_field_references_unknown_table_rejected(self):
        query = make_query(selectedFields=[{'tableId': 'nope', 'columnName': 'id'}])
        with pytest.raises(ValueError, match='unknown table instance'):
            generate(query)


class TestJoins:
    def test_left_join_keeps_direction(self):
        query = make_query()
        query['joins'][0]['type'] = 'LEFT'
        sql, _ = generate(query)
        assert 'FROM "customer" "c"\nLEFT JOIN "order" "o" ON "c"."id" = "o"."customer_id"' in sql

    def test_left_join_direction_independent_of_table_order(self):
        # Reversing the tables array must not flip LEFT JOIN semantics:
        # the left table instance stays the preserved side.
        query = make_query()
        query['joins'][0]['type'] = 'LEFT'
        query['tables'] = list(reversed(query['tables']))
        sql, _ = generate(query)
        assert 'FROM "customer" "c"' in sql
        assert 'LEFT JOIN "order" "o" ON "c"."id" = "o"."customer_id"' in sql

    def test_cross_join_has_no_on_clause(self):
        query = make_query(joins=[
            {'id': 'j1', 'type': 'CROSS', 'leftTableId': 't1', 'rightTableId': 't2',
             'leftTable': 'customer', 'rightTable': 'order'},
        ])
        sql, _ = generate(query)
        assert 'CROSS JOIN "order" "o"' in sql
        assert ' ON ' not in sql

    @pytest.mark.parametrize('join_type', ['RIGHT', 'FULL'])
    def test_unsupported_joins_rejected(self, join_type):
        query = make_query()
        query['joins'][0]['type'] = join_type
        with pytest.raises(ValueError, match=f'{join_type} JOIN is not supported by SQLite'):
            generate(query)

    def test_join_cycle_rejected(self):
        query = make_query(
            tables=[
                {'id': 'a', 'tableName': 'customer', 'alias': 'a'},
                {'id': 'b', 'tableName': 'order', 'alias': 'b'},
                {'id': 'c', 'tableName': 'product', 'alias': 'c'},
            ],
            joins=[
                {'id': 'j1', 'type': 'INNER', 'leftTableId': 'a', 'leftColumn': 'id',
                 'rightTableId': 'b', 'rightColumn': 'customer_id',
                 'leftTable': 'customer', 'rightTable': 'order'},
                {'id': 'j2', 'type': 'INNER', 'leftTableId': 'b', 'leftColumn': 'id',
                 'rightTableId': 'c', 'rightColumn': 'id',
                 'leftTable': 'order', 'rightTable': 'product'},
                {'id': 'j3', 'type': 'INNER', 'leftTableId': 'c', 'leftColumn': 'id',
                 'rightTableId': 'a', 'rightColumn': 'id',
                 'leftTable': 'product', 'rightTable': 'customer'},
            ],
            selectedFields=[{'tableId': 'a', 'columnName': 'id'}],
        )
        with pytest.raises(ValueError, match='cycle'):
            generate(query)

    def test_self_join_uses_instance_aliases(self):
        query = make_query(
            tables=[
                {'id': 'e1', 'tableName': 'employee', 'alias': 'e'},
                {'id': 'e2', 'tableName': 'employee', 'alias': 'm'},
            ],
            joins=[
                {'id': 'j1', 'type': 'LEFT', 'leftTableId': 'e1', 'leftColumn': 'id',
                 'rightTableId': 'e2', 'rightColumn': 'id',
                 'leftTable': 'employee', 'rightTable': 'employee'},
            ],
            selectedFields=[
                {'tableId': 'e1', 'columnName': 'first_name'},
                {'tableId': 'e2', 'columnName': 'first_name'},
            ],
        )
        sql, _ = generate(query)
        assert 'LEFT JOIN "employee" "m" ON "e"."id" = "m"."id"' in sql
        assert '"e"."first_name" AS "e_first_name"' in sql
        assert '"m"."first_name" AS "m_first_name"' in sql


class TestConditions:
    def clause(self, **kw):
        base = {'id': 'c1', 'tableId': 't2', 'columnName': 'total_amount', 'cmp': '>', 'value': 100}
        base.update(kw)
        return base

    def test_nested_and_or_not(self):
        query = make_query(where={
            'id': 'w', 'op': 'AND', 'children': [
                self.clause(),
                {'id': 'n', 'op': 'NOT', 'children': [
                    {'id': 'g', 'op': 'OR', 'children': [
                        {'id': 'c2', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
                        {'id': 'c3', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'UK'},
                    ]},
                ]},
            ],
        })
        sql, params = generate(query)
        assert 'WHERE ("o"."total_amount" > :p1 AND NOT (("c"."country" = :p2 OR "c"."country" = :p3)))' in sql
        assert params['p1'] == 100
        assert params['p2'] == 'US'
        assert params['p3'] == 'UK'

    def test_not_requires_single_child(self):
        query = make_query(where={'id': 'n', 'op': 'NOT', 'children': [self.clause(), self.clause(id='c2')]})
        with pytest.raises(ValueError, match='NOT group requires exactly one child'):
            generate(query)

    def test_invalid_logical_op_rejected(self):
        query = make_query(where={'id': 'x', 'op': 'XOR', 'children': [self.clause()]})
        with pytest.raises(ValueError, match='Invalid logical operator'):
            generate(query)

    def test_is_null_operators_need_no_value(self):
        query = make_query(where={'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't2', 'columnName': 'employee_id', 'cmp': 'IS NULL'},
            {'id': 'c2', 'tableId': 't2', 'columnName': 'employee_id', 'cmp': 'IS NOT NULL'},
        ]})
        sql, params = generate(query)
        assert '"o"."employee_id" IS NULL' in sql
        assert '"o"."employee_id" IS NOT NULL' in sql
        # only the LIMIT parameter is bound
        assert list(params.keys()) == ['p1']

    def test_null_value_maps_to_is_null(self):
        query = make_query(where={'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't2', 'columnName': 'employee_id', 'cmp': '=', 'value': None},
            {'id': 'c2', 'tableId': 't2', 'columnName': 'employee_id', 'cmp': '!=', 'value': None},
        ]})
        sql, _ = generate(query)
        assert '"o"."employee_id" IS NULL' in sql
        assert '"o"."employee_id" IS NOT NULL' in sql

    def test_empty_in_and_not_in(self):
        query = make_query(where={'id': 'w', 'op': 'OR', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'id', 'cmp': 'IN', 'value': []},
            {'id': 'c2', 'tableId': 't1', 'columnName': 'id', 'cmp': 'NOT IN', 'value': []},
        ]})
        sql, params = generate(query)
        assert '((1 = 0) OR (1 = 1))' in sql
        assert list(params.keys()) == ['p1']  # only LIMIT

    def test_in_binds_each_value(self):
        query = make_query(where={'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': 'IN', 'value': ['US', "O'Hara"]},
        ]})
        sql, params = generate(query)
        assert '"c"."country" IN (:p1, :p2)' in sql
        assert params['p1'] == 'US'
        assert params['p2'] == "O'Hara"

    def test_invalid_operator_rejected(self):
        query = make_query(where={'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'id', 'cmp': '=; DROP TABLE x; --', 'value': 1},
        ]})
        with pytest.raises(ValueError, match='Invalid operator'):
            generate(query)


class TestAggregationsAndHaving:
    def test_group_by_and_having(self):
        query = make_query(
            selectedFields=[{'tableId': 't1', 'columnName': 'country'}],
            aggregations=[
                {'tableId': 't2', 'columnName': 'total_amount', 'function': 'SUM', 'alias': 'total'},
                {'tableId': 't2', 'columnName': 'id', 'function': 'COUNT'},
            ],
            having={'id': 'h', 'op': 'AND', 'children': [
                {'id': 'h1', 'tableId': 't2', 'columnName': 'total_amount',
                 'function': 'SUM', 'cmp': '>', 'value': 500},
            ]},
        )
        sql, params = generate(query)
        assert 'SUM("o"."total_amount") AS "total"' in sql
        assert 'COUNT("o"."id") AS "count_id"' in sql
        assert 'GROUP BY "c"."country"' in sql
        assert 'HAVING SUM("o"."total_amount") > :p1' in sql
        assert params['p1'] == 500

    def test_invalid_aggregation_rejected(self):
        query = make_query(aggregations=[
            {'tableId': 't2', 'columnName': 'id', 'function': 'MEDIAN'},
        ])
        with pytest.raises(ValueError, match='Invalid aggregation function'):
            generate(query)


class TestPagination:
    def test_limit_and_offset_are_bound_parameters(self):
        query = make_query(limit=5, offset=20)
        sql, params = generate(query)
        assert 'LIMIT :p1' in sql
        assert 'OFFSET :p2' in sql
        assert params == {'p1': 5, 'p2': 20}
        assert 'LIMIT 5' not in sql

    @pytest.mark.parametrize('bad_limit', [0, -1, 1001, '10', True])
    def test_invalid_limit_rejected(self, bad_limit):
        with pytest.raises(ValueError, match='Limit must be an integer'):
            generate(make_query(limit=bad_limit))

    def test_invalid_offset_rejected(self):
        with pytest.raises(ValueError, match='Offset must be a non-negative integer'):
            generate(make_query(offset=-5))


class TestSubqueriesAndCtes:
    def test_in_subquery_shares_param_namespace(self):
        query = make_query(where={'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'id', 'cmp': 'IN',
             'subquery': {
                 'tables': [{'id': 's1', 'tableName': 'order', 'alias': 'o2'}],
                 'joins': [],
                 'selectedFields': [{'tableId': 's1', 'columnName': 'customer_id'}],
                 'where': {'id': 'sw', 'op': 'AND', 'children': [
                     {'id': 'sc', 'tableId': 's1', 'columnName': 'status', 'cmp': '=', 'value': 'shipped'},
                 ]},
                 'aggregations': [],
                 'limit': 500}},
            {'id': 'c2', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
        ]})
        sql, params = generate(query)
        assert '"c"."id" IN (' in sql
        assert '"o2"."status" = :p1' in sql
        assert '"c"."country" = :p3' in sql
        # params: p1=status value, p2=subquery limit, p3=country, p4=outer limit
        assert params == {'p1': 'shipped', 'p2': 500, 'p3': 'US', 'p4': 100}

    def test_cte_query(self):
        query = make_query(ctes=[{
            'id': 'cte1',
            'name': 'big_orders',
            'queryStructure': {
                'tables': [{'id': 's1', 'tableName': 'order', 'alias': 'o'}],
                'joins': [],
                'selectedFields': [{'tableId': 's1', 'columnName': 'customer_id'}],
                'where': {'id': 'sw', 'op': 'AND', 'children': [
                    {'id': 'sc', 'tableId': 's1', 'columnName': 'total_amount', 'cmp': '>', 'value': 200},
                ]},
                'aggregations': [],
                'limit': 500},
        }])
        sql, params = generate(query)
        assert sql.startswith('WITH "big_orders" AS (')
        assert params['p1'] == 200


class TestInjectionDefense:
    @pytest.mark.parametrize('bad_name', [
        'x"; DROP TABLE customer; --',
        "x' OR '1'='1",
        'x y',
        '1abc',
    ])
    def test_malicious_identifiers_rejected(self, bad_name):
        query = make_query(tables=[{'id': 't1', 'tableName': 'customer', 'alias': bad_name}])
        with pytest.raises(ValueError):
            generate(query)

    def test_malicious_table_name_rejected(self):
        query = make_query(tables=[{'id': 't1', 'tableName': 'customer; DROP TABLE x', 'alias': 'c'}])
        with pytest.raises(ValueError, match='Invalid table name'):
            generate(query)
