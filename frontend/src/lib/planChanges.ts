import type { AstChange, PlanChange } from '@/types';

/**
 * Presentation helpers for plan/version comparison. Every change is
 * localized to an AST node (join edge, filter clause, aggregation, table
 * instance, index access path) - SQL string positions are never used.
 */

export const CATEGORY_LABELS: Record<string, string> = {
  join: 'JOIN',
  filter: 'Filter',
  having: 'Having',
  aggregation: 'Aggregation',
  select: 'Columns',
  table: 'Table',
  pagination: 'Pagination',
  'access-path': 'Index access',
};

export interface GroupedChanges {
  category: string;
  label: string;
  changes: AstChange[];
}

/** Group an AST change set by category in a stable, display-ready order. */
export function groupAstChanges(changes: AstChange[]): GroupedChanges[] {
  const order = ['table', 'join', 'filter', 'having', 'aggregation', 'select', 'pagination'];
  const groups = new Map<string, AstChange[]>();
  for (const change of changes) {
    const list = groups.get(change.category) ?? [];
    list.push(change);
    groups.set(change.category, list);
  }
  return order
    .filter((category) => groups.has(category))
    .map((category) => ({
      category,
      label: CATEGORY_LABELS[category] ?? category,
      changes: groups.get(category)!,
    }));
}

const CHANGE_VERBS: Record<string, string> = {
  added: 'added',
  removed: 'removed',
  modified: 'changed',
};

/** One-line summary of a single AST change, referencing the node id. */
export function formatAstChange(change: AstChange): string {
  const verb = CHANGE_VERBS[change.change] ?? change.change;
  let text = `${change.label} ${verb}`;
  const detail = change.detail;
  if (detail && change.change === 'modified') {
    if ('from' in detail && 'to' in detail) {
      text = `${change.label}: ${detail.from} → ${detail.to}`;
    }
  }
  if (change.nodeId) {
    text += `  [${change.nodeId}]`;
  }
  return text;
}

/** One-line summary of an access-path (index usage) change. */
export function formatPlanChange(change: PlanChange): string {
  const target = change.alias ? `${change.table} (${change.alias})` : (change.table ?? 'plan');
  if (change.change === 'modified' && change.detail?.from && change.detail?.to) {
    const from = change.detail.from;
    const to = change.detail.to;
    const fromText = from.index ? `${from.access} ${from.index}` : from.access;
    const toText = to.index ? `${to.access} ${to.index}` : to.access;
    return `${target}: ${fromText} → ${toText}`;
  }
  if (change.detail?.extra) {
    return `${change.detail.extra} ${CHANGE_VERBS[change.change] ?? change.change}`;
  }
  const access = change.detail?.index
    ? `${change.detail.access} ${change.detail.index}`
    : change.detail?.access;
  return `${target} ${CHANGE_VERBS[change.change] ?? change.change}${access ? ` (${access})` : ''}`;
}
