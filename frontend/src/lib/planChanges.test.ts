import { describe, it, expect } from 'vitest';
import { formatAstChange, formatPlanChange, groupAstChanges } from './planChanges';
import type { AstChange, PlanChange } from '@/types';

/**
 * Change-set presentation tests: every label must reference the AST node
 * (join edge, clause id, table alias, index access) - never a SQL string
 * line number.
 */

describe('groupAstChanges', () => {
  it('groups by category in a stable order', () => {
    const changes: AstChange[] = [
      { category: 'pagination', change: 'modified', nodeId: null, label: 'limit', detail: { from: 100, to: 50 } },
      { category: 'join', change: 'modified', nodeId: 'j1', label: 'c.id = o.customer_id', detail: { from: 'LEFT', to: 'INNER' } },
      { category: 'filter', change: 'added', nodeId: 'c9', label: 'o.status =' },
      { category: 'join', change: 'added', nodeId: 'j2', label: 'o.id = oi.order_id', detail: { type: 'LEFT' } },
    ];
    const groups = groupAstChanges(changes);
    expect(groups.map((g) => g.category)).toEqual(['join', 'filter', 'pagination']);
    expect(groups[0].changes).toHaveLength(2);
    expect(groups[0].label).toBe('JOIN');
    expect(groups[1].label).toBe('Filter');
  });

  it('omits empty categories', () => {
    const groups = groupAstChanges([]);
    expect(groups).toEqual([]);
  });
});

describe('formatAstChange', () => {
  it('localizes a JOIN type change to the join node id', () => {
    const text = formatAstChange({
      category: 'join', change: 'modified', nodeId: 'j1',
      label: 'c.id = o.customer_id', detail: { from: 'LEFT', to: 'INNER' },
    });
    expect(text).toContain('c.id = o.customer_id');
    expect(text).toContain('LEFT');
    expect(text).toContain('INNER');
    expect(text).toContain('[j1]');
    expect(text).not.toMatch(/line \d+/i);
  });

  it('localizes an added filter to its clause id', () => {
    const text = formatAstChange({
      category: 'filter', change: 'added', nodeId: 'c9', label: 'o.status =',
    });
    expect(text).toContain('added');
    expect(text).toContain('o.status =');
    expect(text).toContain('[c9]');
  });

  it('localizes aggregation changes without node id', () => {
    const text = formatAstChange({
      category: 'aggregation', change: 'modified', nodeId: null,
      label: 'SUM(o.total_amount)', detail: { from: 'COUNT', to: 'SUM' },
    });
    expect(text).toContain('COUNT');
    expect(text).toContain('SUM');
  });
});

describe('formatPlanChange', () => {
  it('describes index access changes by table and alias', () => {
    const text = formatPlanChange({
      category: 'access-path', change: 'modified', table: 'order', alias: 'o',
      detail: {
        from: { op: 'SCAN', access: 'full-scan', index: null },
        to: { op: 'SEARCH', access: 'index', index: 'idx_order_status' },
      },
    });
    expect(text).toContain('order (o)');
    expect(text).toContain('full-scan');
    expect(text).toContain('idx_order_status');
  });

  it('describes added plan extras', () => {
    const text = formatPlanChange({
      category: 'access-path', change: 'added', table: null, alias: null,
      detail: { extra: 'USE TEMP B-TREE FOR GROUP BY' },
    });
    expect(text).toContain('TEMP B-TREE');
    expect(text).toContain('added');
  });
});
