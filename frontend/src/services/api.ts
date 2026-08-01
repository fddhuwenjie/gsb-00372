import type { TableMetadata, QueryStructure, GeneratedSQL, QueryResult, SavedQuery, QueryHistoryItem, ExplainResult, ShareResult, ChartConfig } from '@/types';

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
