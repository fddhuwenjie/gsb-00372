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

export interface OrderByItem {
  tableId: string;
  columnName: string;
  direction: 'ASC' | 'DESC';
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
  having: WhereCondition | null;
  aggregations: Aggregation[];
  orderBy: OrderByItem[];
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
  return 'cmp' in node;
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
  params?: Record<string, any>;
  rawPlanRows: any[];
  rawBytecodeRows: any[];
}

export interface ShareResult {
  query: SavedQuery;
  result: QueryResult;
}

export type TabType = 'result' | 'saved' | 'history' | 'plan' | 'share' | 'templates' | 'plan-diff';
export type ResultViewMode = 'table' | 'chart';

export type TemplateParameterType =
  | 'string'
  | 'integer'
  | 'number'
  | 'boolean'
  | 'date'
  | 'string_list'
  | 'integer_list'
  | 'date_range';

export interface TemplateParameter {
  name: string;
  type: TemplateParameterType;
  label?: string;
  description?: string;
  required?: boolean;
  default?: any;
}

export interface SchemaRef {
  tableId: string;
  tableName: string;
  columnName: string;
  location: string;
}

export interface QueryTemplate {
  id: number;
  name: string;
  description: string;
  version: number;
  query_structure: QueryStructure;
  parameters: TemplateParameter[];
  schema_refs: SchemaRef[];
  share_token?: string;
  share_expires_at?: string;
  share_access_count: number;
  created_at: string;
  updated_at: string;
}

export interface TemplateInstantiateResult {
  queryStructure: QueryStructure;
  sql: string;
  params: Record<string, any>;
  templateVersion: number;
}

export interface TemplateValidationResult {
  valid: boolean;
  errors: string[];
}

export interface PlanOperation {
  operation: 'SCAN' | 'SEARCH' | 'TEMP_BTREE' | 'INDEX_SCAN' | 'CORRELATED_SCALAR' | 'SUBQUERY_LIST' | 'OTHER' | null;
  tableName: string | null;
  tableAlias: string | null;
  tableId: string | null;
  indexName: string | null;
  joinId: string | null;
  category: 'table_scan' | 'index_access' | 'compound' | 'other' | null;
  astNodeKeys: string[];
  detail: string;
}

export interface PlanSnapshot {
  id: number;
  templateId: number | null;
  templateVersion: number | null;
  label: string | null;
  astHash: string;
  paramTypeSummary: Record<string, string>;
  normalizedPlan: PlanOperation[];
  planOperations: PlanOperation[];
  rowCount: number;
  durationMs: number;
  createdAt: string;
}

export interface PlanChangedOperation {
  tableId: string;
  tableName: string | null;
  old: PlanOperation;
  new: PlanOperation;
  changedFields: string[];
  astNodeKeys: string[];
}

export interface AstChange {
  astNodeKey: string;
  tableId: string;
  changeType: string;
  oldValue: string;
  newValue: string;
}

export interface PlanDiff {
  added: PlanOperation[];
  removed: PlanOperation[];
  changed: PlanChangedOperation[];
  astChanges: AstChange[];
  summary: {
    added: number;
    removed: number;
    changed: number;
    hasChanges: boolean;
  };
}

export interface PlanCompareResult {
  oldSnapshot?: PlanSnapshot;
  newSnapshot?: PlanSnapshot;
  diff: PlanDiff;
}

export type BatchRunStatus =
  | 'pending' | 'running' | 'completed' | 'cancelled' | 'partially_failed';

export type BatchItemStatus =
  | 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'rejected';

export interface BatchItem {
  id: number;
  batchRunId: number;
  itemIndex: number;
  parameterSummary: Record<string, string>;
  status: BatchItemStatus;
  attemptCount: number;
  rowCount: number;
  durationMs: number;
  error: string | null;
  planSnapshotId: number | null;
  columns?: { name: string; type: string }[];
  rows?: any[][];
  createdAt?: string;
  startedAt?: string;
  completedAt?: string;
}

export interface BatchRun {
  id: number;
  templateId: number;
  templateVersion: number;
  idempotencyKey: string;
  status: BatchRunStatus;
  concurrency: number;
  maxTotalRows: number | null;
  maxDurationMs: number | null;
  totalItems: number;
  succeededCount: number;
  failedCount: number;
  cancelledCount: number;
  rejectedCount: number;
  totalRows: number;
  totalDurationMs: number;
  error: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  items?: BatchItem[];
}
