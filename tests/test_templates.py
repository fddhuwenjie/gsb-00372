"""Template service tests: parameterization is value-only, typed parameters
with defaults / required constraints, AST round-trip (save/share/JSON), and
locatable schema-migration errors.

Covers self-join, NULL, empty IN, date and illegal-type scenarios.
"""
import json
import copy
import pytest

from app.services.template_service import (
    TemplateService, TemplateError, TemplateStructureError,
    ParameterTypeError, MissingParameterError, SchemaMigrationError,
    is_placeholder,
)
from app.services.sql_generator import SQLGenerator


def tables(*specs):
    return [{'id': tid, 'tableName': name, 'alias': alias, 'position': {}}
            for tid, name, alias in specs]


def base_query():
    return {
        'tables': tables(('o', 'order', 'o'), ('c', 'customer', 'c')),
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
                   'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'},
                           {'tableId': 'o', 'columnName': 'total_amount'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'd1', 'tableId': 'o', 'columnName': 'order_date', 'cmp': '>=', 'value': '2025-01-01'},
            {'id': 'ct', 'tableId': 'c', 'columnName': 'country', 'cmp': 'IN', 'value': ['US']}]},
        'aggregations': [], 'limit': 100, 'offset': 0,
    }


def sample_metadata():
    return [
        {'name': 'order', 'columns': [
            {'name': 'id', 'type': 'INTEGER'},
            {'name': 'customer_id', 'type': 'INTEGER'},
            {'name': 'employee_id', 'type': 'INTEGER'},
            {'name': 'order_date', 'type': 'DATE'},
            {'name': 'total_amount', 'type': 'NUMERIC'},
        ]},
        {'name': 'customer', 'columns': [
            {'name': 'id', 'type': 'INTEGER'},
            {'name': 'country', 'type': 'VARCHAR'},
            {'name': 'first_name', 'type': 'VARCHAR'},
        ]},
    ]


def make_template():
    return TemplateService.parameterize(base_query(), [
        {'name': 'start_date', 'type': 'date', 'required': True,
         'target': {'kind': 'filter', 'clauseId': 'd1'}},
        {'name': 'countries', 'type': 'list', 'itemType': 'string', 'default': ['US'],
         'target': {'kind': 'filter', 'clauseId': 'ct'}},
        {'name': 'page_size', 'type': 'integer', 'default': 50,
         'target': {'kind': 'limit'}},
    ])


# --- parameterization is value-only ----------------------------------------
def test_parameterize_replaces_only_values():
    tpl = make_template()
    qs = tpl['queryStructure']
    # Filter values became placeholders; structure untouched.
    where_children = qs['where']['children']
    assert is_placeholder(where_children[0]['value'])
    assert is_placeholder(where_children[1]['value'])
    assert is_placeholder(qs['limit'])
    # Table/column identifiers remain literal strings.
    assert qs['tables'][0]['tableName'] == 'order'
    assert where_children[0]['columnName'] == 'order_date'
    assert {p['name'] for p in tpl['parameters']} == {'start_date', 'countries', 'page_size'}


def test_structural_placeholder_rejected():
    bad = {
        'queryStructure': {
            'tables': [{'id': 'o', 'tableName': {'$param': 'x'}, 'alias': 'o', 'position': {}}],
            'joins': [], 'selectedFields': [], 'where': None, 'aggregations': [], 'limit': 10,
        },
        'parameters': [{'name': 'x', 'type': 'string'}],
    }
    with pytest.raises(TemplateStructureError):
        TemplateService.validate_template(bad)


def test_undeclared_parameter_rejected():
    tpl = make_template()
    tpl['parameters'] = [p for p in tpl['parameters'] if p['name'] != 'countries']
    with pytest.raises(TemplateError):
        TemplateService.validate_template(tpl)


# --- typed resolution -------------------------------------------------------
def test_instantiate_binds_values_into_ast():
    tpl = make_template()
    concrete = TemplateService.instantiate(
        tpl, {'start_date': '2025-03-01', 'countries': ['US', 'UK', 'DE']})
    g = SQLGenerator(concrete)
    sql = g.generate()
    params = g.get_params()
    assert 'order_date' in sql
    assert list(params.values()) == ['2025-03-01', 'US', 'UK', 'DE', 50]


def test_default_applied_when_value_missing():
    tpl = make_template()
    concrete = TemplateService.instantiate(tpl, {'start_date': '2025-01-01'})
    g = SQLGenerator(concrete)
    g.generate()
    params = g.get_params()
    # countries defaults to ['US']; page_size defaults to 50
    assert 'US' in params.values()
    assert 50 in params.values()


def test_required_missing_raises():
    tpl = make_template()
    with pytest.raises(MissingParameterError):
        TemplateService.instantiate(tpl, {'countries': ['US']})


def test_illegal_type_date_raises():
    tpl = make_template()
    with pytest.raises(ParameterTypeError):
        TemplateService.instantiate(tpl, {'start_date': 'not-a-date', 'countries': ['US']})


def test_illegal_type_integer_raises():
    tpl = make_template()
    with pytest.raises(ParameterTypeError):
        TemplateService.instantiate(
            tpl, {'start_date': '2025-01-01', 'countries': ['US'], 'page_size': 'big'})


def test_list_param_wrong_container_raises():
    tpl = make_template()
    with pytest.raises(ParameterTypeError):
        TemplateService.instantiate(
            tpl, {'start_date': '2025-01-01', 'countries': 'US'})


# --- empty IN ---------------------------------------------------------------
def test_empty_in_list_param_generates_false():
    tpl = make_template()
    concrete = TemplateService.instantiate(
        tpl, {'start_date': '2025-01-01', 'countries': []})
    sql = SQLGenerator(concrete).generate()
    assert '(1 = 0)' in sql  # empty IN is always false


# --- NULL / self-join structure preserved ----------------------------------
def test_self_join_with_null_and_param():
    qs = {
        'tables': tables(('a', 'order', 'o1'), ('b', 'order', 'o2')),
        'joins': [{'id': 'j', 'type': 'LEFT', 'leftTableId': 'a', 'leftColumn': 'customer_id',
                   'rightTableId': 'b', 'rightColumn': 'customer_id', 'leftTable': 'order', 'rightTable': 'order'}],
        'selectedFields': [{'tableId': 'a', 'columnName': 'id'}, {'tableId': 'b', 'columnName': 'id'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'f1', 'tableId': 'a', 'columnName': 'total_amount', 'cmp': '>', 'value': 0},
            {'id': 'n', 'tableId': 'b', 'columnName': 'employee_id', 'cmp': 'IS NULL'}]},
        'aggregations': [], 'limit': 10,
    }
    tpl = TemplateService.parameterize(qs, [
        {'name': 'min_total', 'type': 'number', 'default': 0, 'target': {'kind': 'filter', 'clauseId': 'f1'}},
    ])
    concrete = TemplateService.instantiate(tpl, {'min_total': 100})
    g = SQLGenerator(concrete)
    sql = g.generate()
    assert '"o1"' in sql and '"o2"' in sql       # self-join aliases distinct
    assert 'IS NULL' in sql                        # NULL leaf untouched (no param)
    assert 100 in g.get_params().values()


# --- AST round-trip: save / share / JSON -----------------------------------
def test_template_json_roundtrip_stable():
    tpl = make_template()
    reopened = json.loads(json.dumps(tpl))
    a = TemplateService.instantiate(tpl, {'start_date': '2025-02-01', 'countries': ['US', 'UK']})
    b = TemplateService.instantiate(reopened, {'start_date': '2025-02-01', 'countries': ['US', 'UK']})
    ga, gb = SQLGenerator(a), SQLGenerator(b)
    assert ga.generate() == gb.generate()
    assert ga.get_params() == gb.get_params()


def test_template_reference_survives_table_reorder():
    tpl = make_template()
    reordered = copy.deepcopy(tpl)
    reordered['queryStructure']['tables'].reverse()
    a = SQLGenerator(TemplateService.instantiate(tpl, {'start_date': '2025-01-01'})).get_params()
    b = SQLGenerator(TemplateService.instantiate(reordered, {'start_date': '2025-01-01'})).get_params()
    assert a == b  # references bound by id, not position


# --- schema migration errors (locatable) -----------------------------------
def test_schema_ok_passes():
    tpl = make_template()
    concrete = TemplateService.instantiate(
        tpl, {'start_date': '2025-01-01'}, metadata=sample_metadata())
    assert concrete is not None


def test_column_removed_is_locatable():
    tpl = make_template()
    meta = sample_metadata()
    # remove order_date
    meta[0]['columns'] = [c for c in meta[0]['columns'] if c['name'] != 'order_date']
    with pytest.raises(SchemaMigrationError) as exc:
        TemplateService.instantiate(tpl, {'start_date': '2025-01-01'}, metadata=meta)
    refs = exc.value.references
    assert any(r['columnName'] == 'order_date' and r['tableName'] == 'order'
               and r['reason'] == 'column_removed' and r['tableInstanceId'] == 'o'
               for r in refs)


def test_table_removed_is_locatable():
    tpl = make_template()
    meta = [t for t in sample_metadata() if t['name'] != 'customer']
    with pytest.raises(SchemaMigrationError) as exc:
        TemplateService.instantiate(tpl, {'start_date': '2025-01-01'}, metadata=meta)
    assert any(r['reason'] == 'table_removed' and r['tableName'] == 'customer'
               for r in exc.value.references)


def test_type_change_incompatible_with_param_is_locatable():
    tpl = make_template()
    meta = sample_metadata()
    # order_date changes from DATE to INTEGER, but start_date param is a date.
    for col in meta[0]['columns']:
        if col['name'] == 'order_date':
            col['type'] = 'INTEGER'
    with pytest.raises(SchemaMigrationError) as exc:
        TemplateService.instantiate(tpl, {'start_date': '2025-01-01'}, metadata=meta)
    assert any(r['columnName'] == 'order_date' and 'type_incompatible' in r['reason']
               for r in exc.value.references)
