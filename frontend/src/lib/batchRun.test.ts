import { describe, it, expect } from 'vitest';
import { buildBatchItems, canRetry, emptyRow, itemStatusLabel } from './batchRun';
import type { TemplateParameter } from '@/types';

const parameters: TemplateParameter[] = [
  { id: 'p-c', name: 'country', type: 'string', required: true,
    target: { kind: 'where', nodeId: 'c1' } },
  { id: 'p-l', name: 'page_size', type: 'integer', required: false, default: 50,
    target: { kind: 'limit' } },
  { id: 'p-d', name: 'from_date', type: 'date', required: false, default: '2025-01-01',
    target: { kind: 'where', nodeId: 'c2' } },
];

describe('emptyRow', () => {
  it('prefills defaults', () => {
    const row = emptyRow(parameters, 'r1');
    expect(row.raw).toEqual({ country: '', page_size: '50', from_date: '2025-01-01' });
  });
});

describe('buildBatchItems', () => {
  it('builds typed values for every row in order', () => {
    const rows = [
      { key: 'r1', raw: { country: 'US', page_size: '10', from_date: '2025-02-01' } },
      { key: 'r2', raw: { country: 'UK', page_size: '20', from_date: '2025-03-01' } },
    ];
    const { items, rowErrors } = buildBatchItems(parameters, rows);
    expect(rowErrors).toEqual({});
    expect(items).toEqual([
      { values: { country: 'US', page_size: 10, from_date: '2025-02-01' } },
      { values: { country: 'UK', page_size: 20, from_date: '2025-03-01' } },
    ]);
  });

  it('flags invalid rows by row key and parameter name', () => {
    const rows = [
      { key: 'r1', raw: { country: 'US', page_size: '10', from_date: '2025-02-01' } },
      { key: 'r2', raw: { country: 'UK', page_size: 'abc', from_date: 'not-a-date' } },
    ];
    const { rowErrors } = buildBatchItems(parameters, rows);
    expect(Object.keys(rowErrors)).toEqual(['r2']);
    expect(rowErrors.r2.page_size).toContain('integer');
    expect(rowErrors.r2.from_date).toContain('date');
    expect(rowErrors.r2.country).toBeUndefined();
  });

  it('keeps row order stable even with errors', () => {
    const rows = [
      { key: 'r1', raw: { country: 'US', page_size: 'x', from_date: '2025-01-01' } },
      { key: 'r2', raw: { country: 'UK', page_size: '5', from_date: '2025-01-01' } },
    ];
    const { items } = buildBatchItems(parameters, rows);
    expect(items[1].values).toEqual({ country: 'UK', page_size: 5, from_date: '2025-01-01' });
  });
});

describe('status helpers', () => {
  it('canRetry only when not running', () => {
    expect(canRetry('running')).toBe(false);
    for (const status of ['completed', 'cancelled', 'interrupted', 'failed']) {
      expect(canRetry(status)).toBe(true);
    }
  });

  it('labels item statuses', () => {
    expect(itemStatusLabel('succeeded')).toBe('Succeeded');
    expect(itemStatusLabel('skipped')).toBe('Skipped');
  });
});
