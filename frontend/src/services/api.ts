import type { TableMetadata, QueryStructure, GeneratedSQL, QueryResult, SavedQuery, QueryHistoryItem, ExplainResult, ShareResult, ChartConfig, QueryTemplate, TemplateInstantiation, TemplateIssue, TemplateParameter, CompareResult, ExecutionSnapshot, TemplateVersionInfo, BatchRun, BatchRunItem } from '@/types';

const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  issues?: TemplateIssue[];
  constructor(message: string, status: number, issues?: TemplateIssue[]) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

async function throwApiError(response: Response, fallback: string): Promise<never> {
  const body = await response.json().catch(() => ({}));
  throw new ApiError(body.error || fallback, response.status, body.issues);
}

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

// ---------------------------------------------------------------------------
// Parameterized query templates
// ---------------------------------------------------------------------------

export async function getTemplates(): Promise<QueryTemplate[]> {
  const response = await fetch(`${API_BASE}/templates`);
  if (!response.ok) {
    throw new Error('Failed to fetch templates');
  }
  return response.json();
}

export async function createTemplate(data: {
  name: string;
  description?: string;
  parameters: TemplateParameter[];
  query_structure: QueryStructure;
}): Promise<QueryTemplate> {
  const response = await fetch(`${API_BASE}/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    return throwApiError(response, 'Failed to create template');
  }
  return response.json();
}

export async function deleteTemplate(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/templates/${id}`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error('Failed to delete template');
  }
}

export async function instantiateTemplate(
  id: number,
  values: Record<string, unknown>,
  execute = false
): Promise<TemplateInstantiation> {
  const response = await fetch(`${API_BASE}/templates/${id}/instantiate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values, execute }),
  });
  if (!response.ok) {
    return throwApiError(response, 'Failed to instantiate template');
  }
  return response.json();
}

export async function validateTemplate(
  id: number
): Promise<{ valid: boolean; issues: TemplateIssue[]; version: number }> {
  const response = await fetch(`${API_BASE}/templates/${id}/validate`);
  if (!response.ok) {
    return throwApiError(response, 'Failed to validate template');
  }
  return response.json();
}

export async function getTemplateVersions(id: number): Promise<TemplateVersionInfo[]> {
  const response = await fetch(`${API_BASE}/templates/${id}/versions`);
  if (!response.ok) {
    return throwApiError(response, 'Failed to fetch template versions');
  }
  return response.json();
}

export async function compareTemplateVersions(
  id: number,
  body: {
    from_version: number;
    to_version: number;
    values?: Record<string, unknown>;
    include_results?: boolean;
  }
): Promise<CompareResult> {
  const response = await fetch(`${API_BASE}/templates/${id}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    return throwApiError(response, 'Failed to compare template versions');
  }
  return response.json();
}

export async function getExecutions(templateId?: number): Promise<ExecutionSnapshot[]> {
  const url = templateId
    ? `${API_BASE}/executions?template_id=${templateId}`
    : `${API_BASE}/executions`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error('Failed to fetch executions');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Batch parameter runs
// ---------------------------------------------------------------------------

export async function createBatchRun(body: {
  template_id: number;
  version?: number;
  items: { values: Record<string, unknown> }[];
  max_concurrency?: number;
  max_total_rows?: number;
  max_total_time_ms?: number;
  item_timeout_ms?: number;
  item_delay_ms?: number;
  idempotency_key?: string;
}): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batch-runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    return throwApiError(response, 'Failed to create batch run');
  }
  return response.json();
}

export async function getBatchRun(id: number): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batch-runs/${id}`);
  if (!response.ok) {
    return throwApiError(response, 'Failed to fetch batch run');
  }
  return response.json();
}

export async function getBatchRunItems(id: number): Promise<BatchRunItem[]> {
  const response = await fetch(`${API_BASE}/batch-runs/${id}/items`);
  if (!response.ok) {
    return throwApiError(response, 'Failed to fetch batch run items');
  }
  return response.json();
}

export async function cancelBatchRun(id: number): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batch-runs/${id}/cancel`, { method: 'POST' });
  if (!response.ok) {
    return throwApiError(response, 'Failed to cancel batch run');
  }
  return response.json();
}

export async function retryBatchRun(id: number): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batch-runs/${id}/retry`, { method: 'POST' });
  if (!response.ok) {
    return throwApiError(response, 'Failed to retry batch run');
  }
  return response.json();
}
