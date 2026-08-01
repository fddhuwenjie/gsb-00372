import type { TemplateParameter } from '@/types';
import { validateTemplateValue } from './templateParams';

/**
 * Helpers to build batch-run parameter sets from form rows. Every row is
 * validated against the declared parameter types before submission; the
 * backend re-validates per item (failures stay item-local).
 */

export interface BatchFormRow {
  key: string;
  raw: Record<string, string>;
}

export interface BuiltBatchItems {
  items: { values: Record<string, unknown> }[];
  rowErrors: Record<string, Record<string, string>>;
}

/** New empty form row, prefilled with parameter defaults. */
export function emptyRow(parameters: TemplateParameter[], key: string): BatchFormRow {
  const raw: Record<string, string> = {};
  for (const param of parameters) {
    const value = param.default;
    raw[param.name] =
      value === undefined || value === null
        ? ''
        : Array.isArray(value)
          ? value.join(', ')
          : String(value);
  }
  return { key, raw };
}

/**
 * Validate every row and build the API payload. `rowErrors` is keyed by row
 * key then parameter name; submission is allowed only when it is empty.
 */
export function buildBatchItems(
  parameters: TemplateParameter[],
  rows: BatchFormRow[]
): BuiltBatchItems {
  const items: { values: Record<string, unknown> }[] = [];
  const rowErrors: Record<string, Record<string, string>> = {};

  for (const row of rows) {
    const values: Record<string, unknown> = {};
    const errors: Record<string, string> = {};
    for (const param of parameters) {
      const result = validateTemplateValue(param, row.raw[param.name] ?? '');
      if (!result.ok) {
        errors[param.name] = result.error ?? 'invalid value';
      } else {
        values[param.name] = result.value;
      }
    }
    if (Object.keys(errors).length > 0) {
      rowErrors[row.key] = errors;
    }
    items.push({ values });
  }

  return { items, rowErrors };
}

/** Statuses from which a batch can be retried (not running). */
export function canRetry(status: string): boolean {
  return status !== 'running';
}

/** Human label for an item status. */
export function itemStatusLabel(status: string): string {
  return (
    {
      pending: 'Pending',
      running: 'Running',
      succeeded: 'Succeeded',
      failed: 'Failed',
      cancelled: 'Cancelled',
      skipped: 'Skipped',
    }[status] ?? status
  );
}
