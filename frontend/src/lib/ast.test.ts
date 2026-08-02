import { describe, it, expect } from 'vitest';
import {
  allocateAlias,
  createTableInstance,
  isValidIdentifier,
  normalizeQueryStructure,
} from './ast';
import type { QueryStructure } from '@/types';

describe('isValidIdentifier', () => {
  it('accepts valid SQL identifiers', () => {
    expect(isValidIdentifier('customer')).toBe(true);
    expect(isValidIdentifier('order_item')).toBe(true);
    expect(isValidIdentifier('_private')).toBe(true);
    expect(isValidIdentifier('t1')).toBe(true);
  });

  it('rejects invalid identifiers', () => {
    expect(isValidIdentifier('')).toBe(false);
    expect(isValidIdentifier('1table')).toBe(false);
    expect(isValidIdentifier('bad name')).toBe(false);
    expect(isValidIdentifier('a;DROP')).toBe(false);
  });
});

describe('allocateAlias', () => {
  it('returns a short base alias for the first instance', () => {
    const alias = allocateAlias('customer', []);
    expect(alias).toMatch(/^[a-z]/);
    expect(isValidIdentifier(alias)).toBe(true);
  });

  it('disambiguates self-joins by appending a counter', () => {
    const existing = [
      { id: 'a', tableName: 'employee', alias: 'e', position: { x: 0, y: 0 } },
    ];
    const alias = allocateAlias('employee', existing);
    expect(alias).not.toBe('e');
    expect(isValidIdentifier(alias)).toBe(true);
  });

  it('never returns a duplicate alias', () => {
    const existing = [
      { id: 'a', tableName: 'customer', alias: 'c', position: { x: 0, y: 0 } },
      { id: 'b', tableName: 'customer', alias: 'c2', position: { x: 0, y: 0 } },
    ];
    const alias = allocateAlias('customer', existing);
    expect(existing.some((t) => t.alias === alias)).toBe(false);
  });
});

describe('createTableInstance', () => {
  it('produces a stable valid id and unique alias', () => {
    const t1 = createTableInstance('order', [], { x: 0, y: 0 });
    const t2 = createTableInstance('order', [t1], { x: 10, y: 10 });
    expect(isValidIdentifier(t1.id)).toBe(true);
    expect(isValidIdentifier(t2.id)).toBe(true);
    expect(t1.id).not.toBe(t2.id);
    expect(t1.alias).not.toBe(t2.alias);
    expect(t1.tableName).toBe('order');
  });
});

describe('normalizeQueryStructure', () => {
  it('preserves existing stable ids and aliases on save/restore', () => {
    const saved: QueryStructure = {
      tables: [
        { id: 't_mgr', tableName: 'employee', alias: 'mgr', position: { x: 0, y: 0 } },
        { id: 't_emp', tableName: 'employee', alias: 'emp', position: { x: 10, y: 10 } },
      ],
      joins: [{
        id: 'j1', type: 'LEFT',
        leftTableId: 't_mgr', leftColumn: 'id',
        rightTableId: 't_emp', rightColumn: 'id',
        leftTable: 'employee', rightTable: 'employee',
      }],
      selectedFields: [
        { tableId: 't_mgr', columnName: 'last_name', alias: 'manager' },
        { tableId: 't_emp', columnName: 'last_name', alias: 'worker' },
      ],
      where: null,
      aggregations: [],
      limit: 50,
    };
    const restored = normalizeQueryStructure(saved);
    expect(restored.tables[0].id).toBe('t_mgr');
    expect(restored.tables[0].alias).toBe('mgr');
    expect(restored.tables[1].id).toBe('t_emp');
    expect(restored.tables[1].alias).toBe('emp');
    // field references remain bound to their original table instance
    expect(restored.selectedFields[0].tableId).toBe('t_mgr');
    expect(restored.selectedFields[1].tableId).toBe('t_emp');
  });

  it('fills in missing ids/aliases for legacy data', () => {
    const legacy = {
      tables: [
        { tableName: 'customer', position: { x: 0, y: 0 } },
        { tableName: 'customer', position: { x: 1, y: 1 } },
      ],
      joins: [],
      selectedFields: [],
      aggregations: [],
      limit: 10,
    } as unknown as QueryStructure;
    const normalized = normalizeQueryStructure(legacy);
    expect(normalized.tables.every((t) => isValidIdentifier(t.id))).toBe(true);
    expect(normalized.tables.every((t) => isValidIdentifier(t.alias))).toBe(true);
    const aliases = normalized.tables.map((t) => t.alias);
    expect(new Set(aliases).size).toBe(aliases.length);
  });

  it('round-trips through JSON without losing table bindings', () => {
    const original: QueryStructure = {
      tables: [
        { id: 'c', tableName: 'customer', alias: 'c', position: { x: 0, y: 0 } },
        { id: 'o', tableName: 'order', alias: 'o', position: { x: 1, y: 1 } },
      ],
      joins: [{
        id: 'j1', type: 'INNER',
        leftTableId: 'c', leftColumn: 'id',
        rightTableId: 'o', rightColumn: 'customer_id',
        leftTable: 'customer', rightTable: 'order',
      }],
      selectedFields: [
        { tableId: 'c', columnName: 'country' },
        { tableId: 'o', columnName: 'total_amount' },
      ],
      where: {
        id: 'w_root',
        op: 'AND',
        children: [
          { id: 'w1', tableId: 'o', columnName: 'total_amount', cmp: '>', value: 100 },
        ],
      },
      aggregations: [
        { tableId: 'o', columnName: 'total_amount', function: 'SUM', alias: 'total' },
      ],
      having: null,
      orderBy: [{ tableId: 'c', columnName: 'country', direction: 'ASC' }],
      limit: 25,
      offset: 5,
    };
    const json = JSON.stringify(original);
    const restored = normalizeQueryStructure(JSON.parse(json));
    expect(restored).toEqual(original);
    // selected fields must stay bound to the correct table instance even
    // though both tables could have identically-named columns
    expect(restored.selectedFields[0].tableId).toBe('c');
    expect(restored.selectedFields[1].tableId).toBe('o');
  });

  it('defaults pagination values', () => {
    const qs = normalizeQueryStructure({
      tables: [{ id: 't', tableName: 'x', alias: 'x', position: { x: 0, y: 0 } }],
      selectedFields: [],
      joins: [],
      aggregations: [],
    } as unknown as QueryStructure);
    expect(qs.limit).toBe(100);
    expect(qs.offset).toBe(0);
    expect(qs.orderBy).toEqual([]);
    expect(qs.having).toBeNull();
  });
});
