import { describe, it, expect, beforeEach } from 'vitest';
import { useQueryStore, createTableInstance } from './queryStore';
import type { QueryStructure, SavedQuery, WhereCondition } from '@/types';

/**
 * AST round-trip tests: an AST built through the store must survive
 * JSON serialization (save), reopen (loadQueryStructure / loadQuery) and
 * share-restore without any change to table instance ids, aliases, field
 * bindings or condition trees. The frontend never rebuilds SQL locally;
 * fidelity of this structure is what guarantees unambiguous semantics.
 */

function buildComplexState() {
  const store = useQueryStore.getState();
  const t1 = createTableInstance('customer', { x: 0, y: 0 }, []);
  const t2 = createTableInstance('order', { x: 200, y: 0 }, [t1]);
  const t3 = createTableInstance('customer', { x: 400, y: 0 }, [t1, t2]); // self-join instance
  store.addTable(t1);
  store.addTable(t2);
  store.addTable(t3);

  store.addJoin({
    id: 'join-1',
    type: 'INNER',
    leftTableId: t1.id,
    leftColumn: 'id',
    rightTableId: t2.id,
    rightColumn: 'customer_id',
    leftTable: 'customer',
    rightTable: 'order',
  });
  store.addJoin({
    id: 'join-2',
    type: 'LEFT',
    leftTableId: t1.id,
    leftColumn: 'id',
    rightTableId: t3.id,
    rightColumn: 'id',
    leftTable: 'customer',
    rightTable: 'customer',
  });

  store.toggleField(t1.id, 'id', true);
  store.toggleField(t2.id, 'id', true);
  store.toggleField(t3.id, 'first_name', true);

  const where: WhereCondition = {
    id: 'w1',
    op: 'AND',
    children: [
      { id: 'c1', tableId: t2.id, columnName: 'total_amount', cmp: '>', value: 100 },
      {
        id: 'n1',
        op: 'NOT',
        children: [
          { id: 'c2', tableId: t1.id, columnName: 'country', cmp: 'IN', value: ['US', 'UK'] },
        ],
      },
      { id: 'c3', tableId: t2.id, columnName: 'employee_id', cmp: 'IS NULL' },
      { id: 'c4', tableId: t1.id, columnName: 'id', cmp: 'NOT IN', value: [] },
    ],
  };
  store.setWhere(where);

  store.addAggregation({ tableId: t2.id, columnName: 'total_amount', function: 'SUM', alias: 'total' });
  store.setHaving({
    id: 'h1',
    op: 'AND',
    children: [
      { id: 'hc1', tableId: t2.id, columnName: 'total_amount', function: 'SUM', cmp: '>', value: 500 },
    ],
  });
  store.setLimit(25);
  store.setOffset(50);

  return { t1, t2, t3 };
}

beforeEach(() => {
  useQueryStore.getState().clearAll();
});

describe('createTableInstance', () => {
  it('assigns unique aliases for self-joins of the same table', () => {
    const a = createTableInstance('customer', { x: 0, y: 0 }, []);
    const b = createTableInstance('customer', { x: 0, y: 0 }, [a]);
    const c = createTableInstance('customer', { x: 0, y: 0 }, [a, b]);
    expect(new Set([a.alias, b.alias, c.alias]).size).toBe(3);
    expect(a.alias).toBe('cu');
    expect(b.alias).toBe('cu2');
    expect(c.alias).toBe('cu3');
  });

  it('disambiguates shared prefixes across different tables', () => {
    const order = createTableInstance('order', { x: 0, y: 0 }, []);
    const orderItem = createTableInstance('order_item', { x: 0, y: 0 }, [order]);
    expect(order.alias).not.toBe(orderItem.alias);
  });

  it('assigns unique stable ids', () => {
    const a = createTableInstance('customer', { x: 0, y: 0 }, []);
    const b = createTableInstance('customer', { x: 0, y: 0 }, [a]);
    expect(a.id).not.toBe(b.id);
  });
});

describe('AST round trips', () => {
  it('survives a JSON save/reopen round trip unchanged', () => {
    const { t1, t2, t3 } = buildComplexState();
    const ast = useQueryStore.getState().getQueryStructure();

    // simulate persistence: exactly what the backend stores as JSON
    const persisted = JSON.parse(JSON.stringify(ast)) as QueryStructure;

    useQueryStore.getState().clearAll();
    expect(useQueryStore.getState().tables).toHaveLength(0);

    useQueryStore.getState().loadQueryStructure(persisted);
    const restored = useQueryStore.getState().getQueryStructure();

    expect(restored).toEqual(ast);
    // stable instance ids / aliases preserved verbatim
    expect(restored.tables.map((t) => t.id)).toEqual([t1.id, t2.id, t3.id]);
    expect(restored.tables.map((t) => t.alias)).toEqual([t1.alias, t2.alias, t3.alias]);
    // field references stay bound to their table instance
    expect(restored.selectedFields[0].tableId).toBe(t1.id);
    expect(restored.joins[1].rightTableId).toBe(t3.id);
    expect(restored.having).toEqual(ast.having);
    expect(restored.offset).toBe(50);
  });

  it('survives a saved-query loadQuery round trip unchanged', () => {
    buildComplexState();
    const ast = useQueryStore.getState().getQueryStructure();

    const savedQuery: SavedQuery = {
      id: 42,
      name: 'roundtrip',
      description: '',
      query_structure: JSON.parse(JSON.stringify(ast)),
      share_access_count: 0,
      created_at: '2026-01-01T00:00:00',
      updated_at: '2026-01-01T00:00:00',
    };

    useQueryStore.getState().clearAll();
    useQueryStore.getState().loadQuery(savedQuery);

    expect(useQueryStore.getState().getQueryStructure()).toEqual(ast);
    expect(useQueryStore.getState().currentSavedId).toBe(42);
  });

  it('survives a share-restore round trip unchanged', () => {
    buildComplexState();
    const ast = useQueryStore.getState().getQueryStructure();

    // share payload: { query: SavedQuery, result: ... } -> frontend loads query.query_structure
    const sharedStructure = JSON.parse(JSON.stringify(ast)) as QueryStructure;

    useQueryStore.getState().clearAll();
    useQueryStore.getState().loadQueryStructure(sharedStructure);

    expect(useQueryStore.getState().getQueryStructure()).toEqual(ast);
  });

  it('keeps aliases unique when adding another self-join instance after restore', () => {
    const { t1 } = buildComplexState();
    const ast = useQueryStore.getState().getQueryStructure();

    useQueryStore.getState().loadQueryStructure(JSON.parse(JSON.stringify(ast)));

    const existing = useQueryStore.getState().tables;
    const extra = createTableInstance('customer', { x: 600, y: 0 }, existing);
    useQueryStore.getState().addTable(extra);

    const aliases = useQueryStore.getState().tables.map((t) => t.alias);
    expect(new Set(aliases).size).toBe(aliases.length);
    expect(extra.alias).not.toBe(t1.alias);
  });

  it('removeTable keeps the AST consistent (joins, fields, aggregations)', () => {
    const { t2 } = buildComplexState();
    useQueryStore.getState().removeTable(t2.id);

    const ast = useQueryStore.getState().getQueryStructure();
    expect(ast.tables.find((t) => t.id === t2.id)).toBeUndefined();
    expect(ast.joins.every((j) => j.leftTableId !== t2.id && j.rightTableId !== t2.id)).toBe(true);
    expect(ast.selectedFields.every((f) => f.tableId !== t2.id)).toBe(true);
    expect(ast.aggregations.every((a) => a.tableId !== t2.id)).toBe(true);
  });

  it('produces a deterministic structure on repeated reads', () => {
    buildComplexState();
    const first = useQueryStore.getState().getQueryStructure();
    const second = useQueryStore.getState().getQueryStructure();
    expect(second).toEqual(first);
  });
});
