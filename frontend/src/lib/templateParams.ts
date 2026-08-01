import type {
  QueryStructure, TableMetadata, TemplateParameter, TemplateParameterType,
  WhereClause, WhereNode,
} from '@/types';
import { isWhereCondition } from '@/types';

/**
 * Value-level helpers for parameterized templates: inferring parameter
 * types from schema metadata, deriving parameter declarations from an AST,
 * and validating form input before it is sent to the instantiate API.
 * No SQL is built here - the backend remains the only SQL authority.
 */

const LIST_OPERATORS = new Set(['IN', 'NOT IN']);
const NO_VALUE_OPERATORS = new Set(['IS NULL', 'IS NOT NULL', 'EXISTS', 'NOT EXISTS']);

/** Map a schema column type (e.g. 'INTEGER', 'VARCHAR(50)', 'DATE') to a
 * scalar parameter type. */
export function inferScalarType(columnType: string): TemplateParameterType {
  const base = (columnType || '').split('(')[0].trim().toUpperCase();
  if (['INT', 'INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT'].includes(base)) return 'integer';
  if (['NUMERIC', 'DECIMAL', 'REAL', 'FLOAT', 'DOUBLE'].includes(base)) return 'number';
  if (['DATE', 'DATETIME', 'TIMESTAMP'].includes(base)) return 'date';
  if (['BOOLEAN', 'BOOL'].includes(base)) return 'boolean';
  return 'string';
}

export function inferParamType(columnType: string, isList: boolean): TemplateParameterType {
  const scalar = inferScalarType(columnType);
  if (!isList) return scalar;
  if (scalar === 'integer') return 'integer[]';
  if (scalar === 'number') return 'number[]';
  return 'string[]';
}

function* walkClauses(node: WhereNode | null): Generator<WhereClause> {
  if (!node) return;
  if (isWhereCondition(node)) {
    for (const child of node.children) {
      yield* walkClauses(child);
    }
  } else if ('cmp' in node) {
    yield node;
  }
}

function findColumnType(
  metadata: TableMetadata[],
  structure: QueryStructure,
  tableId: string,
  columnName: string
): string {
  const table = structure.tables.find((t) => t.id === tableId);
  const meta = metadata.find((m) => m.name === table?.tableName);
  const column = meta?.columns.find((c) => c.name === columnName);
  return column?.type || '';
}

function sanitizeName(input: string): string {
  return input.replace(/[^a-zA-Z0-9_]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || 'param';
}

/**
 * Derive parameter declarations from an AST: every value-bearing where /
 * having clause becomes a parameter (default = current value, type inferred
 * from the column's schema type), plus pagination parameters for limit and
 * offset. Targets reference clauses by their stable clause id, so the
 * mapping survives save / share / schema-refresh round trips.
 */
export function deriveParameters(
  structure: QueryStructure,
  metadata: TableMetadata[]
): TemplateParameter[] {
  const parameters: TemplateParameter[] = [];
  const usedNames = new Set<string>();

  const uniqueName = (base: string): string => {
    let name = base;
    let n = 2;
    while (usedNames.has(name)) {
      name = `${base}_${n}`;
      n += 1;
    }
    usedNames.add(name);
    return name;
  };

  for (const kind of ['where', 'having'] as const) {
    for (const clause of walkClauses(structure[kind] ?? null)) {
      if (NO_VALUE_OPERATORS.has(clause.cmp) || clause.subquery) continue;
      const table = structure.tables.find((t) => t.id === clause.tableId);
      const columnType = findColumnType(metadata, structure, clause.tableId, clause.columnName);
      const isList = LIST_OPERATORS.has(clause.cmp);
      const type = inferParamType(columnType, isList);
      const baseName = sanitizeName(
        `${table?.alias || 't'}_${clause.columnName}${isList ? '_list' : ''}`
      );
      const name = uniqueName(baseName);
      parameters.push({
        id: `param-${clause.id}`,
        name,
        type,
        required: false,
        default: clause.value,
        target: { kind, nodeId: clause.id },
      });
    }
  }

  parameters.push({
    id: 'param-limit',
    name: uniqueName('page_size'),
    type: 'integer',
    required: false,
    default: structure.limit,
    target: { kind: 'limit' },
  });
  if (structure.offset) {
    parameters.push({
      id: 'param-offset',
      name: uniqueName('page_offset'),
      type: 'integer',
      required: false,
      default: structure.offset,
      target: { kind: 'offset' },
    });
  }

  return parameters;
}

// ---------------------------------------------------------------------------
// Form-level value validation (mirrors backend coercion rules)
// ---------------------------------------------------------------------------

export interface ValidationResult {
  ok: boolean;
  value?: unknown;
  error?: string;
}

const INTEGER_RE = /^-?\d+$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidDate(value: string): boolean {
  if (!DATE_RE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function coerceScalar(type: TemplateParameterType, raw: string): ValidationResult {
  const trimmed = raw.trim();
  switch (type) {
    case 'string':
      return { ok: true, value: raw };
    case 'integer':
      if (!INTEGER_RE.test(trimmed)) {
        return { ok: false, error: `expected integer, got '${raw}'` };
      }
      return { ok: true, value: parseInt(trimmed, 10) };
    case 'number': {
      const num = Number(trimmed);
      if (trimmed === '' || isNaN(num)) {
        return { ok: false, error: `expected number, got '${raw}'` };
      }
      return { ok: true, value: num };
    }
    case 'boolean': {
      const lower = trimmed.toLowerCase();
      if (lower === 'true') return { ok: true, value: true };
      if (lower === 'false') return { ok: true, value: false };
      return { ok: false, error: `expected boolean (true/false), got '${raw}'` };
    }
    case 'date':
      if (!isValidDate(trimmed)) {
        return { ok: false, error: `expected ISO date (YYYY-MM-DD), got '${raw}'` };
      }
      return { ok: true, value: trimmed };
    case 'datetime':
      if (isNaN(new Date(trimmed.replace(' ', 'T')).getTime())) {
        return { ok: false, error: `expected ISO datetime, got '${raw}'` };
      }
      return { ok: true, value: trimmed };
    default:
      return { ok: false, error: `unknown parameter type '${type}'` };
  }
}

/**
 * Validate a raw form string against the declared parameter type.
 * List types accept comma-separated input; an empty string is an empty list
 * (which the backend turns into (1 = 0) for IN / (1 = 1) for NOT IN).
 * Returns the coerced value ready for the instantiate API.
 */
export function validateTemplateValue(
  param: TemplateParameter,
  raw: string
): ValidationResult {
  if (param.type.endsWith('[]')) {
    const itemType = param.type.slice(0, -2) as TemplateParameterType;
    const items = raw.split(',').map((s) => s.trim()).filter((s) => s !== '');
    const values: unknown[] = [];
    for (const item of items) {
      const result = coerceScalar(itemType, item);
      if (!result.ok) {
        return { ok: false, error: `item '${item}': ${result.error}` };
      }
      values.push(result.value);
    }
    return { ok: true, value: values };
  }
  return coerceScalar(param.type, raw);
}

/** Initial raw form string for a parameter (prefilled from its default). */
export function defaultRawValue(param: TemplateParameter): string {
  const value = param.default;
  if (value === undefined || value === null) return '';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}
