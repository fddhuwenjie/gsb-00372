import type { TableMetadata, QueryStructure, GeneratedSQL, QueryResult, SavedQuery, QueryHistoryItem, ExplainResult, ShareResult, ChartConfig, QueryTemplate, TemplateParameter, TemplateInstantiateResult, TemplateValidationResult, PlanSnapshot, PlanDiff, PlanCompareResult, BatchRun } from '@/types';

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

export async function getTemplates(): Promise<QueryTemplate[]> {
  const response = await fetch(`${API_BASE}/templates`);
  if (!response.ok) throw new Error('Failed to fetch templates');
  return response.json();
}

export async function getTemplate(id: number): Promise<QueryTemplate> {
  const response = await fetch(`${API_BASE}/templates/${id}`);
  if (!response.ok) throw new Error('Failed to fetch template');
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
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to create template');
  }
  return response.json();
}

export async function updateTemplate(
  id: number,
  data: Partial<{
    name: string;
    description: string;
    query_structure: QueryStructure;
    parameters: TemplateParameter[];
  }>
): Promise<QueryTemplate> {
  const response = await fetch(`${API_BASE}/templates/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to update template');
  }
  return response.json();
}

export async function deleteTemplate(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/templates/${id}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to delete template');
}

export async function instantiateTemplate(
  id: number,
  parameters: Record<string, any>
): Promise<TemplateInstantiateResult> {
  const response = await fetch(`${API_BASE}/templates/${id}/instantiate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parameters }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to instantiate template');
  }
  return response.json();
}

export async function executeTemplate(
  id: number,
  parameters: Record<string, any>
): Promise<QueryResult> {
  const response = await fetch(`${API_BASE}/templates/${id}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parameters }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to execute template');
  }
  return response.json();
}

export async function validateTemplate(id: number): Promise<TemplateValidationResult> {
  const response = await fetch(`${API_BASE}/templates/${id}/validate`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to validate template');
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
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to share template');
  }
  return response.json();
}

export async function getSharedTemplate(token: string): Promise<{ template: QueryTemplate }> {
  const response = await fetch(`${API_BASE}/share/template/${token}`);
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to load shared template');
  }
  return response.json();
}

// --- Plan snapshot and comparison ---

export async function getPlanSnapshots(templateId?: number): Promise<PlanSnapshot[]> {
  const url = templateId
    ? `${API_BASE}/plan/snapshots?template_id=${templateId}`
    : `${API_BASE}/plan/snapshots`;
  const response = await fetch(url);
  if (!response.ok) throw new Error('Failed to fetch snapshots');
  return response.json();
}

export async function getPlanSnapshot(id: number): Promise<PlanSnapshot> {
  const response = await fetch(`${API_BASE}/plan/snapshots/${id}`);
  if (!response.ok) throw new Error('Failed to fetch snapshot');
  return response.json();
}

export async function createPlanSnapshot(data: {
  query_structure: QueryStructure;
  label?: string;
  template_id?: number;
  template_version?: number;
  parameters?: TemplateParameter[];
}): Promise<PlanSnapshot> {
  const response = await fetch(`${API_BASE}/plan/snapshots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to create snapshot');
  }
  return response.json();
}

export async function comparePlanSnapshots(
  oldId: number,
  newId: number
): Promise<PlanDiff> {
  const response = await fetch(`${API_BASE}/plan/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ oldSnapshotId: oldId, newSnapshotId: newId }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to compare plans');
  }
  return response.json();
}

export async function comparePlanStructures(
  oldStructure: QueryStructure,
  newStructure: QueryStructure
): Promise<PlanDiff> {
  const response = await fetch(`${API_BASE}/plan/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ oldStructure, newStructure }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to compare plans');
  }
  return response.json();
}

export async function compareTemplateVersions(
  templateId: number,
  versionA?: number,
  versionB?: number
): Promise<PlanCompareResult> {
  const params = new URLSearchParams();
  if (versionA) params.set('versionA', String(versionA));
  if (versionB) params.set('versionB', String(versionB));
  const qs = params.toString() ? `?${params}` : '';
  const response = await fetch(`${API_BASE}/plan/compare/template/${templateId}${qs}`);
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to compare template versions');
  }
  return response.json();
}

// --- Batch runs ---

export async function createBatchRun(data: {
  template_id: number;
  parameter_sets: Record<string, any>[];
  concurrency?: number;
  max_total_rows?: number;
  max_duration_ms?: number;
  idempotency_key?: string;
  label?: string;
}): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to create batch');
  }
  return response.json();
}

export async function getBatchRuns(templateId?: number): Promise<BatchRun[]> {
  const url = templateId
    ? `${API_BASE}/batches?template_id=${templateId}`
    : `${API_BASE}/batches`;
  const response = await fetch(url);
  if (!response.ok) throw new Error('Failed to fetch batches');
  return response.json();
}

export async function getBatchRun(id: number): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batches/${id}`);
  if (!response.ok) throw new Error('Failed to fetch batch');
  return response.json();
}

export async function cancelBatchRun(id: number): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batches/${id}/cancel`, { method: 'POST' });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to cancel batch');
  }
  return response.json();
}

export async function retryBatchRun(id: number): Promise<BatchRun> {
  const response = await fetch(`${API_BASE}/batches/${id}/retry`, { method: 'POST' });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || 'Failed to retry batch');
  }
  return response.json();
}
