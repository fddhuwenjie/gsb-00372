export interface ColumnMetadata {
  name: string;
  type: string;
  nullable: boolean;
  isPrimaryKey: boolean;
}

export interface ForeignKey {
  constraintName: string;
  fromColumn: string;
  toTable: string;
  toColumn: string;
}

export interface TableMetadata {
  name: string;
  columns: ColumnMetadata[];
  foreignKeys: ForeignKey[];
}

export interface TableNode {
  id: string;
  tableName: string;
  alias: string;
  position: { x: number; y: number };
}

export type JoinType = 'INNER' | 'LEFT' | 'CROSS';

export interface Join {
  id: string;
  type: JoinType;
  leftTableId: string;
  leftColumn: string;
  rightTableId: string;
  rightColumn: string;
  leftTable: string;
  rightTable: string;
}

export interface SelectedField {
  tableId: string;
  columnName: string;
  alias?: string;
}

export type ComparisonOperator =
  | '=' | '!=' | '>' | '<' | '>=' | '<='
  | 'LIKE' | 'IN' | 'NOT IN'
  | 'IS NULL' | 'IS NOT NULL'
  | 'EXISTS' | 'NOT EXISTS';

export interface WhereClause {
  tableId: string;
  columnName: string;
  cmp: ComparisonOperator;
  value?: string | number | boolean | null | (string | number)[];
  id: string;
  function?: AggregationFunction;
  subquery?: QueryStructure;
}

export interface WhereCondition {
  op: 'AND' | 'OR' | 'NOT';
  children: (WhereCondition | WhereClause)[];
  id: string;
}

export type AggregationFunction = 'SUM' | 'AVG' | 'COUNT' | 'MAX' | 'MIN';

export interface Aggregation {
  tableId: string;
  columnName: string;
  function: AggregationFunction;
  alias?: string;
}

export interface CTE {
  id: string;
  name: string;
  queryStructure: QueryStructure;
}

export interface QueryStructure {
  tables: TableNode[];
  joins: Join[];
  selectedFields: SelectedField[];
  where: WhereCondition | null;
  having?: WhereCondition | null;
  aggregations: Aggregation[];
  limit: number;
  offset?: number;
  ctes?: CTE[];
}

export interface GeneratedSQL {
  sql: string;
  params: Record<string, any>;
}

export interface ResultColumn {
  name: string;
  type: string;
}

export interface QueryResult {
  columns: ResultColumn[];
  rows: any[][];
  executionTime: number;
  rowCount: number;
  truncated?: boolean;
  sql?: string;
  params?: Record<string, any>;
}

export type WhereNode = WhereCondition | WhereClause;

export function isWhereCondition(node: WhereNode): node is WhereCondition {
  return 'op' in node && 'children' in node;
}

export function isWhereClause(node: WhereNode): node is WhereClause {
  return 'columnName' in node && 'cmp' in node;
}

export type ChartType = 'line' | 'bar' | 'pie' | 'scatter';

export interface ChartConfig {
  type: ChartType;
  xField: string;
  yField: string;
  seriesField?: string;
  title?: string;
}

export interface SavedQuery {
  id: number;
  name: string;
  description: string;
  query_structure: QueryStructure;
  chart_config?: ChartConfig;
  share_token?: string;
  share_expires_at?: string;
  share_access_count: number;
  created_at: string;
  updated_at: string;
}

export interface QueryHistoryItem {
  id: number;
  user_session: string;
  query_structure: QueryStructure;
  sql: string;
  params: Record<string, any>;
  duration: number;
  row_count: number;
  created_at: string;
}

export interface ExplainPlanNode {
  id: string;
  parentId: string | null;
  detail: string;
  tableName: string | null;
  indexName: string | null;
  estimatedRows: number | null;
  isFullScan: boolean;
  children: ExplainPlanNode[];
}

export interface ExplainPlanEdge {
  id: string;
  source: string;
  target: string;
}

export interface ExplainResult {
  queryPlan: {
    nodes: ExplainPlanNode[];
    edges: ExplainPlanEdge[];
    roots: ExplainPlanNode[];
  };
  bytecode: any[];
  sql: string;
  rawPlanRows: any[];
  rawBytecodeRows: any[];
}

export interface ShareResult {
  query: SavedQuery;
  result: QueryResult;
}

export type TabType = 'result' | 'saved' | 'history' | 'plan' | 'share' | 'templates';
export type ResultViewMode = 'table' | 'chart';

// ---------------------------------------------------------------------------
// Parameterized query templates
// ---------------------------------------------------------------------------

export type TemplateParameterType =
  | 'string' | 'integer' | 'number' | 'boolean' | 'date' | 'datetime'
  | 'string[]' | 'integer[]' | 'number[]';

export interface TemplateParamTarget {
  kind: 'where' | 'having' | 'limit' | 'offset';
  nodeId?: string;
}

export interface TemplateParameter {
  id: string;
  name: string;
  type: TemplateParameterType;
  required: boolean;
  default?: unknown;
  target: TemplateParamTarget;
}

/** Locatable migration/validation issue returned by the backend. */
export interface TemplateIssue {
  code: string;
  path: string;
  message: string;
  parameter?: string;
  table?: string;
  tableAlias?: string;
  column?: string;
  expected?: string | string[];
  actual?: string;
  target?: string;
}

export interface QueryTemplate {
  id: number;
  name: string;
  description: string;
  version: number;
  parameters: TemplateParameter[];
  query_structure: QueryStructure;
  share_token?: string;
  share_expires_at?: string;
  share_access_count: number;
  created_at: string;
  updated_at: string;
}

export interface TemplateInstantiation {
  query_structure: QueryStructure;
  template_id: number;
  version: number;
  sql: string;
  params: Record<string, any>;
  result?: QueryResult;
}

// ---------------------------------------------------------------------------
// Execution-plan comparison
// ---------------------------------------------------------------------------

export interface PlanAccessNode {
  op: 'SCAN' | 'SEARCH';
  table: string;
  alias: string | null;
  index: string | null;
  using: string | null;
  access: 'full-scan' | 'index' | 'covering-index';
}

export interface NormalizedPlan {
  nodes: PlanAccessNode[];
  extras: string[];
}

export interface ExecutionSnapshot {
  id: number;
  template_id: number | null;
  template_version: number | null;
  ast_hash: string;
  params_summary: Record<string, string>;
  plan_json: NormalizedPlan;
  duration_ms: number;
  row_count: number;
  created_at: string;
}

export interface AstChange {
  category: 'table' | 'join' | 'filter' | 'having' | 'aggregation' | 'select' | 'pagination';
  change: 'added' | 'removed' | 'modified';
  nodeId: string | null;
  label: string;
  alias?: string;
  detail?: Record<string, unknown>;
}

export interface PlanChange {
  category: 'access-path';
  change: 'added' | 'removed' | 'modified';
  table: string | null;
  alias: string | null;
  detail: Record<string, any>;
}

export interface ResultDiff {
  columns_added: string[];
  columns_removed: string[];
  rows_from: number;
  rows_to: number;
  rows_only_in_from: number;
  rows_only_in_to: number;
  duration_from_ms: number;
  duration_to_ms: number;
}

export interface CompareResult {
  from_version: number;
  to_version: number;
  ast_hash_from: string;
  ast_hash_to: string;
  ast_changes: AstChange[];
  plan_changes: PlanChange[];
  plan_from: NormalizedPlan;
  plan_to: NormalizedPlan;
  result_diff: ResultDiff | null;
}

export interface TemplateVersionInfo {
  version: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Batch parameter runs
// ---------------------------------------------------------------------------

export type BatchRunStatus = 'running' | 'completed' | 'cancelled' | 'interrupted' | 'failed';
export type BatchItemStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'skipped';

export interface BatchRun {
  id: number;
  template_id: number;
  template_version: number;
  status: BatchRunStatus;
  stopped_reason: string | null;
  idempotency_key: string | null;
  total_items: number;
  succeeded_items: number;
  failed_items: number;
  cancelled_items: number;
  skipped_items: number;
  max_concurrency: number;
  max_total_rows: number;
  max_total_time_ms: number;
  cancel_requested: boolean;
  total_rows: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface BatchRunItem {
  id: number;
  batch_run_id: number;
  seq: number;
  status: BatchItemStatus;
  params_summary: Record<string, string>;
  ast_hash: string | null;
  sql: string | null;
  plan_json: NormalizedPlan | null;
  row_count: number | null;
  truncated: boolean;
  duration_ms: number | null;
  error: string | null;
  error_code: string | null;
  started_ts: number | null;
  finished_ts: number | null;
}
