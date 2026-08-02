import type { TableMetadata, QueryStructure, GeneratedSQL, QueryResult, SavedQuery, QueryHistoryItem, ExplainResult, ShareResult, ChartConfig, QueryTemplate, TemplateParameter, TemplateDefinition, ParameterizeSpec, SchemaMigrationRef, ExecutionPlanRecord, PlanComparison, BatchRun } from '@/types';

const API_BASE = '/api';

export async function getMetadata(): Promise<TableMetadata[]> {
  const response = await fetch(`${API_BASE}/metadata`);
  if (!response.ok) {
    throw new Error('Failed to fetch metadata');
  }
  return response.json();
}

export async function generateSQL(query: QueryStructure): Promise<GeneratedSQL> {
  const response = await fetch(`${API_BASE}/generate-sql`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(query),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to generate SQL');
  }
  return response.json();
}

export async function executeQuery(query: QueryStructure): Promise<QueryResult> {
  const response = await fetch(`${API_BASE}/execute-query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(query),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to execute query');
  }
  return response.json();
}

export async function explainQuery(query: QueryStructure): Promise<ExplainResult> {
  const response = await fetch(`${API_BASE}/explain`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(query),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to explain query');
  }
  return response.json();
}

export async function getSavedQueries(): Promise<SavedQuery[]> {
  const response = await fetch(`${API_BASE}/queries`);
  if (!response.ok) {
    throw new Error('Failed to fetch saved queries');
  }
  return response.json();
}

export async function createSavedQuery(data: {
  name: string;
  description?: string;
  query_structure: QueryStructure;
  chart_config?: ChartConfig;
}): Promise<SavedQuery> {
  const response = await fetch(`${API_BASE}/queries`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to create saved query');
  }
  return response.json();
}

export async function updateSavedQuery(
  id: number,
  data: Partial<{
    name: string;
    description: string;
    query_structure: QueryStructure;
    chart_config: ChartConfig;
  }>
): Promise<SavedQuery> {
  const response = await fetch(`${API_BASE}/queries/${id}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to update saved query');
  }
  return response.json();
}

export async function deleteSavedQuery(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/queries/${id}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error('Failed to delete saved query');
  }
}

export async function shareQuery(id: number, expiresInHours?: number): Promise<{ token: string; url: string; expires_at?: string }> {
  const response = await fetch(`${API_BASE}/queries/${id}/share`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ expires_in_hours: expiresInHours }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to share query');
  }
  return response.json();
}

export async function getSharedQuery(token: string): Promise<ShareResult> {
  const response = await fetch(`${API_BASE}/share/${token}`);
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to load shared query');
  }
  return response.json();
}

export async function exportQuery(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/queries/${id}/export`);
  if (!response.ok) {
    throw new Error('Failed to export query');
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const contentDisposition = response.headers.get('Content-Disposition');
  const filename = contentDisposition?.match(/filename="(.+)"/)?.[1] || 'query.sql';
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}

export async function getQueryHistory(): Promise<QueryHistoryItem[]> {
  const response = await fetch(`${API_BASE}/history`);
  if (!response.ok) {
    throw new Error('Failed to fetch query history');
  }
  return response.json();
}

export async function getOpenAPI(): Promise<any> {
  const response = await fetch(`${API_BASE}/openapi.json`);
  if (!response.ok) {
    throw new Error('Failed to fetch OpenAPI spec');
  }
  return response.json();
}

// --- Templates -------------------------------------------------------------

async function parseError(response: Response, fallback: string): Promise<never> {
  let body: any = {};
  try {
    body = await response.json();
  } catch {
    // ignore
  }
  const err = new Error(body.error || fallback) as Error & { migration?: SchemaMigrationRef[]; status?: number };
  err.migration = body.migration;
  err.status = response.status;
  throw err;
}

export async function getTemplates(): Promise<QueryTemplate[]> {
  const response = await fetch(`${API_BASE}/templates`);
  if (!response.ok) throw new Error('Failed to fetch templates');
  return response.json();
}

export async function getTemplate(id: number): Promise<QueryTemplate> {
  const response = await fetch(`${API_BASE}/templates/${id}`);
  if (!response.ok) return parseError(response, 'Failed to fetch template');
  return response.json();
}

export async function parameterizeQuery(
  query_structure: QueryStructure,
  specs: ParameterizeSpec[]
): Promise<TemplateDefinition> {
  const response = await fetch(`${API_BASE}/templates/parameterize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query_structure, specs }),
  });
  if (!response.ok) return parseError(response, 'Failed to parameterize query');
  return response.json();
}

export async function createTemplate(data: {
  name: string;
  description?: string;
  query_structure: QueryStructure;
  parameters: TemplateParameter[];
}): Promise<QueryTemplate> {
  const response = await fetch(`${API_BASE}/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) return parseError(response, 'Failed to create template');
  return response.json();
}

export async function updateTemplate(
  id: number,
  data: Partial<{ name: string; description: string; query_structure: QueryStructure; parameters: TemplateParameter[] }>
): Promise<QueryTemplate> {
  const response = await fetch(`${API_BASE}/templates/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) return parseError(response, 'Failed to update template');
  return response.json();
}

export async function deleteTemplate(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/templates/${id}`, { method: 'DELETE' });
  if (!response.ok) return parseError(response, 'Failed to delete template');
}

export async function instantiateTemplate(
  id: number,
  values: Record<string, any>,
  opts?: { version?: number; mode?: 'execute' | 'sql' | 'explain' }
): Promise<QueryResult> {
  const response = await fetch(`${API_BASE}/templates/${id}/instantiate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values, version: opts?.version, mode: opts?.mode || 'execute' }),
  });
  if (!response.ok) return parseError(response, 'Failed to instantiate template');
  return response.json();
}

export async function checkTemplateSchema(
  id: number
): Promise<{ ok: boolean; migration: SchemaMigrationRef[]; error?: string }> {
  const response = await fetch(`${API_BASE}/templates/${id}/check-schema`);
  return response.json();
}

export async function shareTemplate(
  id: number,
  expiresInHours?: number
): Promise<{ token: string; url: string; expires_at?: string }> {
  const response = await fetch(`${API_BASE}/templates/${id}/share`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expires_in_hours: expiresInHours }),
  });
  if (!response.ok) return parseError(response, 'Failed to share template');
  return response.json();
}

// --- Execution plan comparison ---------------------------------------------

export async function recordTemplatePlan(
  id: number,
  values: Record<string, any>,
  version?: number
): Promise<ExecutionPlanRecord> {
  const response = await fetch(`${API_BASE}/templates/${id}/plan-record`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values, version }),
  });
  if (!response.ok) return parseError(response, 'Failed to record plan');
  return response.json();
}

export async function listTemplatePlanRecords(
  id: number,
  version?: number
): Promise<ExecutionPlanRecord[]> {
  const qs = version !== undefined ? `?version=${version}` : '';
  const response = await fetch(`${API_BASE}/templates/${id}/plan-records${qs}`);
  if (!response.ok) return parseError(response, 'Failed to list plan records');
  return response.json();
}

export async function compareTemplatePlans(
  id: number,
  versionA: number,
  versionB: number,
  values: Record<string, any>,
  fresh = false
): Promise<PlanComparison> {
  const response = await fetch(`${API_BASE}/templates/${id}/compare-plans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ versionA, versionB, values, fresh }),
  });
  if (!response.ok) return parseError(response, 'Failed to compare plans');
  return response.json();
}

// --- Cancellable batch parameter runs --------------------------------------

export async function submitBatchRun(
  templateId: number,
  body: {
    value_sets: Record<string, any>[];
    version?: number;
    max_concurrency?: number;
    max_total_rows?: number;
    max_total_ms?: number;
    per_item_timeout_ms?: number;
    per_item_max_rows?: number;
    idempotency_key?: string;
  }
): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/templates/${templateId}/batch-runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) return parseError(response, 'Failed to submit batch run');
  return response.json();
}

export async function getBatchRun(batchId: number): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batch-runs/${batchId}`);
  if (!response.ok) return parseError(response, 'Failed to fetch batch run');
  return response.json();
}

export async function cancelBatchRun(batchId: number): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batch-runs/${batchId}/cancel`, { method: 'POST' });
  if (!response.ok) return parseError(response, 'Failed to cancel batch run');
  return response.json();
}

export async function retryBatchRun(
  batchId: number,
  valueSets: Record<string, any>[]
): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batch-runs/${batchId}/retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value_sets: valueSets }),
  });
  if (!response.ok) return parseError(response, 'Failed to retry batch run');
  return response.json();
}
