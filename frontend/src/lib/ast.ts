import { v4 as uuidv4 } from 'uuid';
import type {
  TableNode,
  Join,
  QueryStructure,
  WhereNode,
  TemplateDefinition,
  TemplateParameter,
  WhereClause,
} from '@/types';

/**
 * AST helpers for the visual query builder.
 *
 * The backend (SQLGenerator) is the sole source of truth for SQL semantics.
 * The frontend only builds and validates the AST; it never constructs SQL
 * strings. Every table instance has a stable `id` and a unique `alias` so
 * that self-joins, duplicate column names, JOIN reordering, save/reopen
 * and share/restore are never ambiguous.
 */

const IDENT_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

export function isValidIdentifier(name: string): boolean {
  return IDENT_RE.test(name);
}

function baseAlias(tableName: string): string {
  const cleaned = tableName.replace(/[^a-zA-Z0-9_]/g, '_');
  const initials = cleaned
    .split('_')
    .filter(Boolean)
    .map((part) => part[0]!.toLowerCase())
    .join('');
  return (initials || 't').substring(0, 3);
}

/**
 * Generate a unique alias for a new table instance, taking self-joins and
 * already-present aliases into account.
 */
export function allocateAlias(
  tableName: string,
  existingTables: TableNode[],
): string {
  const used = new Set(existingTables.map((t) => t.alias));
  const base = baseAlias(tableName);
  if (!used.has(base)) return base;
  let counter = 2;
  while (used.has(`${base}${counter}`)) counter++;
  return `${base}${counter}`;
}

export function createTableInstance(
  tableName: string,
  existingTables: TableNode[],
  position: { x: number; y: number },
): TableNode {
  return {
    id: `t_${uuidv4().replace(/-/g, '').substring(0, 12)}`,
    tableName,
    alias: allocateAlias(tableName, existingTables),
    position,
  };
}

/**
 * Normalize a query structure loaded from disk / share link: assign any
 * missing ids, and ensure every table instance has a unique, valid alias.
 * Existing ids/aliases are preserved so saved queries stay stable.
 */
export function normalizeQueryStructure(
  structure: Partial<QueryStructure>,
): QueryStructure {
  const tables: TableNode[] = (structure.tables ?? []).map((t, index) => {
    const id = t.id && isValidIdentifier(t.id) ? t.id : `t_${index}_${uuidv4().substring(0, 8)}`;
    let alias = t.alias;
    if (!alias || !isValidIdentifier(alias)) {
      alias = baseAlias(t.tableName);
    }
    return { ...t, id, alias };
  });

  const usedAliases = new Set<string>();
  for (const table of tables) {
    let alias = table.alias;
    if (usedAliases.has(alias)) {
      const base = baseAlias(table.tableName);
      let counter = 2;
      while (usedAliases.has(`${base}${counter}`)) counter++;
      alias = `${base}${counter}`;
    }
    usedAliases.add(alias);
    table.alias = alias;
  }

  const joins: Join[] = (structure.joins ?? []).map((j) => ({
    ...j,
    id: j.id || `j_${uuidv4().substring(0, 8)}`,
  }));

  return {
    tables,
    joins,
    selectedFields: structure.selectedFields ?? [],
    where: (structure.where as WhereNode | null) ?? null,
    having: (structure.having as WhereNode | null) ?? null,
    aggregations: structure.aggregations ?? [],
    orderBy: structure.orderBy ?? [],
    limit: structure.limit ?? 100,
    offset: structure.offset ?? 0,
    limitParam: structure.limitParam,
    offsetParam: structure.offsetParam,
    ctes: structure.ctes,
  };
}

// ---------------------------------------------------------------------------
// Template AST helpers
// ---------------------------------------------------------------------------

export const TEMPLATE_VERSION = 1;

/**
 * Create a WHERE/HAVING leaf that references a declared template parameter
 * instead of carrying an inline value. The backend resolves and binds the
 * value at instantiation time; the query AST structure is never altered.
 */
export function createParamClause(
  tableId: string,
  columnName: string,
  cmp: WhereClause['cmp'],
  paramName: string,
  id?: string,
): WhereClause {
  return {
    id: id ?? `wc_${uuidv4().substring(0, 8)}`,
    tableId,
    columnName,
    cmp,
    param: paramName,
  };
}

/**
 * Build a date-window pair: BETWEEN-like AND of two parameter references.
 * Returns a WhereCondition tree suitable for use as a WHERE/HAVING root.
 */
export function createDateWindowCondition(
  tableId: string,
  columnName: string,
  startParam: string,
  endParam: string,
): WhereNode {
  return {
    id: `dw_${uuidv4().substring(0, 8)}`,
    op: 'AND',
    children: [
      createParamClause(tableId, columnName, '>=', startParam),
      createParamClause(tableId, columnName, '<=', endParam),
    ],
  };
}

/**
 * Collect every parameter name referenced by a query AST (conditions,
 * pagination). Used to verify that all declared parameters are used.
 */
export function collectParamReferences(qs: QueryStructure): Set<string> {
  const refs = new Set<string>();
  const walk = (node: any) => {
    if (!node) return;
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (typeof node === 'object') {
      if (typeof node.param === 'string') refs.add(node.param);
      if (typeof node.limitParam === 'string') refs.add(node.limitParam);
      if (typeof node.offsetParam === 'string') refs.add(node.offsetParam);
      Object.values(node).forEach(walk);
    }
  };
  walk(qs);
  return refs;
}

/**
 * Build a well-formed template definition from a query AST and parameter
 * declarations. Every parameter referenced by the AST must be declared, and
 * vice-versa, so saved/shared templates are self-consistent.
 */
export function buildTemplateDefinition(
  name: string,
  queryStructure: QueryStructure,
  parameters: TemplateParameter[],
  description = '',
): TemplateDefinition {
  const declared = new Set(parameters.map((p) => p.name));
  const referenced = collectParamReferences(queryStructure);

  const missing = [...referenced].filter((r) => !declared.has(r));
  if (missing.length > 0) {
    throw new Error(
      `Query references undeclared parameters: ${missing.join(', ')}`,
    );
  }
  const unused = [...declared].filter((d) => !referenced.has(d));
  if (unused.length > 0) {
    throw new Error(
      `Declared parameters not used by query: ${unused.join(', ')}`,
    );
  }

  return {
    template_version: TEMPLATE_VERSION,
    name,
    description,
    parameters,
    queryStructure,
  };
}

/**
 * Normalise a template definition loaded from the server or shared link,
 * ensuring stable ids/aliases in the embedded query structure.
 */
export function normalizeTemplateDefinition(
  def: Partial<TemplateDefinition>,
): TemplateDefinition {
  return {
    template_version: def.template_version ?? TEMPLATE_VERSION,
    name: def.name ?? '',
    description: def.description ?? '',
    parameters: def.parameters ?? [],
    queryStructure: normalizeQueryStructure(def.queryStructure ?? {}),
  };
}
