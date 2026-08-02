import { describe, it, expect } from 'vitest';
import {
  TEMPLATE_VERSION,
  createParamClause,
  createDateWindowCondition,
  collectParamReferences,
  buildTemplateDefinition,
  normalizeTemplateDefinition,
  createTableInstance,
  allocateAlias,
} from './ast';
import type { QueryStructure, TemplateParameter } from '@/types';

function customerOrderQuery(overrides: Partial<QueryStructure> = {}): QueryStructure {
  const c = createTableInstance('customer', [], { x: 0, y: 0 });
  const o = createTableInstance('order', [c], { x: 10, y: 0 });
  return {
    tables: [c, o],
    joins: [{
      id: 'j1', type: 'INNER',
      leftTableId: c.id, leftColumn: 'id',
      rightTableId: o.id, rightColumn: 'customer_id',
      leftTable: 'customer', rightTable: 'order',
    }],
    selectedFields: [
      { tableId: c.id, columnName: 'id' },
      { tableId: o.id, columnName: 'total_amount' },
    ],
    where: null,
    aggregations: [],
    limit: 50,
    ...overrides,
  };
}

describe('createParamClause', () => {
  it('creates a leaf bound to a declared parameter', () => {
    const clause = createParamClause('c', 'country', '=', 'country_filter');
    expect(clause.param).toBe('country_filter');
    expect(clause.tableId).toBe('c');
    expect(clause.columnName).toBe('country');
    expect(clause.cmp).toBe('=');
    expect('value' in clause).toBe(false);
  });
});

describe('createDateWindowCondition', () => {
  it('builds an AND of two date parameter references', () => {
    const cond = createDateWindowCondition(
      'o', 'order_date', 'start_date', 'end_date',
    );
    if (!('op' in cond) || cond.op !== 'AND') {
      throw new Error('expected AND condition');
    }
    expect(cond.children).toHaveLength(2);
    const start = cond.children[0] as { param: string; cmp: string };
    const end = cond.children[1] as { param: string; cmp: string };
    expect(start.param).toBe('start_date');
    expect(start.cmp).toBe('>=');
    expect(end.param).toBe('end_date');
    expect(end.cmp).toBe('<=');
  });
});

describe('collectParamReferences', () => {
  it('finds parameter references in where and pagination', () => {
    const qs = customerOrderQuery({
      where: {
        id: 'w1',
        op: 'AND',
        children: [
          createParamClause('c', 'country', '=', 'country'),
          createParamClause('o', 'total_amount', '>', 'min_amount'),
        ],
      },
      limitParam: 'page_size',
    });
    const refs = collectParamReferences(qs);
    expect(refs.has('country')).toBe(true);
    expect(refs.has('min_amount')).toBe(true);
    expect(refs.has('page_size')).toBe(true);
  });
});

describe('buildTemplateDefinition', () => {
  const params: TemplateParameter[] = [
    { name: 'country', type: 'string', required: true, label: 'Country' },
    { name: 'min_amount', type: 'number', required: false, default: 0 },
  ];

  it('builds a valid definition with version 1', () => {
    const qs = customerOrderQuery({
      where: {
        id: 'w1',
        op: 'AND',
        children: [
          createParamClause('c', 'country', '=', 'country'),
          createParamClause('o', 'total_amount', '>', 'min_amount'),
        ],
      },
    });
    const def = buildTemplateDefinition('Test', qs, params);
    expect(def.template_version).toBe(TEMPLATE_VERSION);
    expect(def.name).toBe('Test');
    expect(def.parameters).toHaveLength(2);
  });

  it('rejects undeclared parameter references', () => {
    const qs = customerOrderQuery({
      where: createParamClause('c', 'country', '=', 'nonexistent'),
    });
    expect(() => buildTemplateDefinition('Bad', qs, [])).toThrow(/undeclared/);
  });

  it('rejects unused declared parameters', () => {
    const qs = customerOrderQuery({ where: null });
    expect(() => buildTemplateDefinition('Bad', qs, params)).toThrow(/not used/);
  });

  it('round-trips through JSON preserving table bindings', () => {
    const c = createTableInstance('customer', [], { x: 0, y: 0 });
    const o = createTableInstance('order', [c], { x: 10, y: 0 });
    const qs: QueryStructure = {
      tables: [c, o],
      joins: [{
        id: 'j1', type: 'INNER',
        leftTableId: c.id, leftColumn: 'id',
        rightTableId: o.id, rightColumn: 'customer_id',
        leftTable: 'customer', rightTable: 'order',
      }],
      selectedFields: [
        { tableId: c.id, columnName: 'id' },
        { tableId: o.id, columnName: 'total_amount' },
      ],
      where: createParamClause(c.id, 'country', '=', 'country'),
      aggregations: [],
      limit: 50,
    };
    const def = buildTemplateDefinition('RT', qs, [params[0]]);
    const restored = normalizeTemplateDefinition(
      JSON.parse(JSON.stringify(def)),
    );
    expect(restored.queryStructure.tables[0].id).toBe(c.id);
    const where = restored.queryStructure.where as unknown as {
      param: string;
      tableId: string;
    };
    expect(where.param).toBe('country');
    expect(where.tableId).toBe(c.id);
  });
});

describe('self-join template AST roundtrip', () => {
  it('preserves distinct aliases and parameter bindings', () => {
    const e1 = createTableInstance('employee', [], { x: 0, y: 0 });
    const e2 = createTableInstance('employee', [e1], { x: 10, y: 0 });
    // Ensure distinct aliases for the same physical table
    expect(e1.alias).not.toBe(e2.alias);

    const qs: QueryStructure = {
      tables: [e1, e2],
      joins: [{
        id: 'j1', type: 'INNER',
        leftTableId: e1.id, leftColumn: 'department',
        rightTableId: e2.id, rightColumn: 'department',
        leftTable: 'employee', rightTable: 'employee',
      }],
      selectedFields: [
        { tableId: e1.id, columnName: 'id', alias: 'mgr' },
        { tableId: e2.id, columnName: 'id', alias: 'worker' },
      ],
      where: createParamClause(e1.id, 'department', '=', 'dept'),
      aggregations: [],
      limit: 100,
    };

    const def = buildTemplateDefinition('Self join', qs, [
      { name: 'dept', type: 'string', required: false, default: 'Sales' },
    ]);

    const json = JSON.stringify(def);
    const restored = normalizeTemplateDefinition(JSON.parse(json));

    expect(restored.queryStructure.tables[0].alias).not.toBe(
      restored.queryStructure.tables[1].alias,
    );
    const selected = restored.queryStructure.selectedFields;
    expect(selected[0].tableId).not.toBe(selected[1].tableId);
    const where = restored.queryStructure.where as { tableId: string };
    expect(where.tableId).toBe(e1.id);
  });
});

describe('empty IN list template', () => {
  it('references a string_list parameter that may be empty', () => {
    const qs = customerOrderQuery({
      where: createParamClause('c', 'country', 'IN', 'countries'),
    });
    const def = buildTemplateDefinition('Empty IN', qs, [
      { name: 'countries', type: 'string_list', required: false, default: [] },
    ]);
    expect(def.parameters[0].type).toBe('string_list');
  });
});

describe('date window template', () => {
  it('declares start and end date parameters', () => {
    const qs = customerOrderQuery({
      where: createDateWindowCondition('o', 'order_date', 'start', 'end'),
    });
    const def = buildTemplateDefinition('Dates', qs, [
      { name: 'start', type: 'date', required: true, usage: 'date_window_start' },
      { name: 'end', type: 'date', required: true, usage: 'date_window_end' },
    ]);
    expect(def.parameters).toHaveLength(2);
    const refs = collectParamReferences(def.queryStructure);
    expect(refs.has('start')).toBe(true);
    expect(refs.has('end')).toBe(true);
  });
});
