import { describe, it, expect, beforeEach } from 'vitest';
import {
  deriveParameters, inferScalarType, inferParamType,
  validateTemplateValue, defaultRawValue,
} from './templateParams';
import { useQueryStore, createTableInstance } from '@/store/queryStore';
import type { QueryStructure, TableMetadata, TemplateParameter } from '@/types';

/**
 * Template AST round-trip tests: parameter declarations derived from an AST
 * must reference stable table-instance ids and clause ids, and those
 * references must survive JSON save/share round trips unchanged. Also
 * covers form-level value validation for NULL, empty IN, dates and
 * illegal types. (The backend re-validates everything; this is the
 * form's first line of feedback.)
 */

const metadata: TableMetadata[] = [
  {
    name: 'customer',
    columns: [
      { name: 'id', type: 'INTEGER', nullable: false, isPrimaryKey: true },
      { name: 'first_name', type: 'VARCHAR(50)', nullable: false, isPrimaryKey: false },
      { name: 'country', type: 'VARCHAR(100)', nullable: true, isPrimaryKey: false },
    ],
    foreignKeys: [],
  },
  {
    name: 'order',
    columns: [
      { name: 'id', type: 'INTEGER', nullable: false, isPrimaryKey: true },
      { name: 'customer_id', type: 'INTEGER', nullable: false, isPrimaryKey: false },
      { name: 'order_date', type: 'DATE', nullable: false, isPrimaryKey: false },
      { name: 'employee_id', type: 'INTEGER', nullable: true, isPrimaryKey: false },
      { name: 'total_amount', type: 'NUMERIC(12, 2)', nullable: true, isPrimaryKey: false },
    ],
    foreignKeys: [
      { constraintName: 'fk', fromColumn: 'customer_id', toTable: 'customer', toColumn: 'id' },
    ],
  },
];

function buildSelfJoinStructure(): { structure: QueryStructure; t1: string; t2: string } {
  const store = useQueryStore.getState();
  store.clearAll();
  const t1 = createTableInstance('customer', { x: 0, y: 0 }, []);
  const t2 = createTableInstance('customer', { x: 200, y: 0 }, [t1]);
  store.addTable(t1);
  store.addTable(t2);
  store.addJoin({
    id: 'j1', type: 'INNER',
    leftTableId: t1.id, leftColumn: 'country',
    rightTableId: t2.id, rightColumn: 'country',
    leftTable: 'customer', rightTable: 'customer',
  });
  store.toggleField(t1.id, 'first_name', true);
  store.toggleField(t2.id, 'country', true);
  store.setWhere({
    id: 'w1', op: 'AND', children: [
      { id: 'c1', tableId: t1.id, columnName: 'country', cmp: '=', value: 'US' },
      { id: 'c2', tableId: t2.id, columnName: 'country', cmp: 'IN', value: ['US', 'UK'] },
      { id: 'c3', tableId: t2.id, columnName: 'id', cmp: 'IS NULL' },
    ],
  });
  store.setLimit(25);
  store.setOffset(50);
  return { structure: store.getQueryStructure(), t1: t1.id, t2: t2.id };
}

beforeEach(() => {
  useQueryStore.getState().clearAll();
});

describe('type inference', () => {
  it('maps schema column types to parameter types', () => {
    expect(inferScalarType('INTEGER')).toBe('integer');
    expect(inferScalarType('NUMERIC(12, 2)')).toBe('number');
    expect(inferScalarType('VARCHAR(50)')).toBe('string');
    expect(inferScalarType('DATE')).toBe('date');
    expect(inferScalarType('BOOLEAN')).toBe('boolean');
    expect(inferParamType('INTEGER', true)).toBe('integer[]');
    expect(inferParamType('VARCHAR(100)', true)).toBe('string[]');
    expect(inferParamType('DATE', false)).toBe('date');
  });
});

describe('deriveParameters', () => {
  it('derives params bound to stable clause ids, skipping NULL operators', () => {
    const { structure, t1, t2 } = buildSelfJoinStructure();
    const params = deriveParameters(structure, metadata);

    const byTarget = new Map(params.map((p) => [p.target.nodeId, p]));
    // c1/c2 are parameterized, c3 (IS NULL) is not
    expect(byTarget.has('c1')).toBe(true);
    expect(byTarget.has('c2')).toBe(true);
    expect(byTarget.has('c3')).toBe(false);

    // defaults come from the current AST values
    expect(byTarget.get('c1')?.default).toBe('US');
    expect(byTarget.get('c1')?.type).toBe('string');
    // IN clause becomes a list parameter
    expect(byTarget.get('c2')?.type).toBe('string[]');
    expect(byTarget.get('c2')?.default).toEqual(['US', 'UK']);

    // pagination parameters
    const limit = params.find((p) => p.target.kind === 'limit');
    const offset = params.find((p) => p.target.kind === 'offset');
    expect(limit?.default).toBe(25);
    expect(offset?.default).toBe(50);

    // parameter names are unique even for the self-join (same column twice)
    const names = params.map((p) => p.name);
    expect(new Set(names).size).toBe(names.length);
    expect(t1).not.toBe(t2);
  });
});

describe('template definition round trips', () => {
  it('keeps instance/field references through JSON save & share round trips', () => {
    const { structure, t1, t2 } = buildSelfJoinStructure();
    const parameters = deriveParameters(structure, metadata);

    const definition = {
      name: 'roundtrip-template',
      version: 1,
      parameters,
      query_structure: structure,
    };

    // save (persist as JSON), then share/restore (parse back)
    const restored = JSON.parse(JSON.stringify(definition));

    expect(restored.query_structure.tables.map((t: { id: string }) => t.id)).toEqual([t1, t2]);
    expect(restored.query_structure.tables.map((t: { alias: string }) => t.alias))
      .toEqual(['cu', 'cu2']);
    expect(restored.parameters).toEqual(parameters);
    // targets still point at the same stable clause ids
    const targetIds = restored.parameters
      .map((p: TemplateParameter) => p.target.nodeId)
      .filter(Boolean);
    expect(targetIds).toEqual(['c1', 'c2']);
  });

  it('restored definition can be loaded back into the store without drift', () => {
    const { structure } = buildSelfJoinStructure();
    const persisted = JSON.parse(JSON.stringify(structure)) as QueryStructure;

    useQueryStore.getState().loadQueryStructure(persisted);
    const reloaded = useQueryStore.getState().getQueryStructure();

    // parameters derived after restore are identical to those derived before
    expect(deriveParameters(reloaded, metadata)).toEqual(
      deriveParameters(structure, metadata)
    );
  });
});

describe('validateTemplateValue (form validation)', () => {
  const param = (type: TemplateParameter['type']): TemplateParameter => ({
    id: 'p', name: 'p', type, required: true, target: { kind: 'where', nodeId: 'c1' },
  });

  it('accepts valid values per type', () => {
    expect(validateTemplateValue(param('string'), 'hello')).toEqual({ ok: true, value: 'hello' });
    expect(validateTemplateValue(param('integer'), ' -42 ')).toEqual({ ok: true, value: -42 });
    expect(validateTemplateValue(param('number'), '3.14')).toEqual({ ok: true, value: 3.14 });
    expect(validateTemplateValue(param('boolean'), 'true')).toEqual({ ok: true, value: true });
    expect(validateTemplateValue(param('date'), '2025-02-28')).toEqual({ ok: true, value: '2025-02-28' });
  });

  it('rejects illegal types with locatable messages', () => {
    for (const raw of ['abc', '1.5', '1e3', '']) {
      const result = validateTemplateValue(param('integer'), raw);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.error).toContain('integer');
    }
    expect(validateTemplateValue(param('date'), '2025-13-01').ok).toBe(false);
    expect(validateTemplateValue(param('date'), 'not-a-date').ok).toBe(false);
    expect(validateTemplateValue(param('boolean'), 'yes').ok).toBe(false);
    expect(validateTemplateValue(param('number'), 'x').ok).toBe(false);
  });

  it('rejects impossible calendar dates', () => {
    expect(validateTemplateValue(param('date'), '2025-02-30').ok).toBe(false);
    expect(validateTemplateValue(param('date'), '2025-06-15').ok).toBe(true);
  });

  it('treats empty list input as an empty IN list', () => {
    expect(validateTemplateValue(param('string[]'), '')).toEqual({ ok: true, value: [] });
    expect(validateTemplateValue(param('string[]'), '  ')).toEqual({ ok: true, value: [] });
    expect(validateTemplateValue(param('string[]'), 'US, UK')).toEqual({ ok: true, value: ['US', 'UK'] });
    expect(validateTemplateValue(param('integer[]'), '1, 2, 3')).toEqual({ ok: true, value: [1, 2, 3] });
    const bad = validateTemplateValue(param('integer[]'), '1, x');
    expect(bad.ok).toBe(false);
  });

  it('keeps injection-looking strings as plain values', () => {
    const result = validateTemplateValue(param('string'), "US' OR '1'='1");
    expect(result).toEqual({ ok: true, value: "US' OR '1'='1" });
  });

  it('prefills form raw values from defaults', () => {
    expect(defaultRawValue(param('string'))).toBe('');
    expect(defaultRawValue({ ...param('integer'), default: 25 })).toBe('25');
    expect(defaultRawValue({ ...param('string[]'), default: ['US', 'UK'] })).toBe('US, UK');
    expect(defaultRawValue({ ...param('date'), default: '2025-01-01' })).toBe('2025-01-01');
  });
});
