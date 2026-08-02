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
  | '='
  | '!='
  | '<>'
  | '>'
  | '<'
  | '>='
  | '<='
  | 'LIKE'
  | 'NOT LIKE'
  | 'IN'
  | 'NOT IN'
  | 'IS NULL'
  | 'IS NOT NULL'
  | 'EXISTS'
  | 'NOT EXISTS';

export interface WhereClause {
  tableId: string;
  columnName: string;
  cmp: ComparisonOperator;
  value?: string | number | boolean | null | (string | number | boolean | null)[];
  /**
   * When present, references a declared template parameter by name. The
   * value is supplied at instantiation time and bound as a SQL parameter;
   * the AST structure is never modified.
   */
  param?: string;
  id: string;
  subquery?: QueryStructure;
}

export interface WhereCondition {
  op: 'AND' | 'OR';
  children: WhereNode[];
  id: string;
}

export interface NotCondition {
  op: 'NOT';
  child: WhereCondition | WhereClause;
  id: string;
}

export type WhereNode = WhereCondition | NotCondition | WhereClause;

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

export interface OrderByField {
  tableId: string;
  columnName: string;
  direction?: 'ASC' | 'DESC';
}

export interface QueryStructure {
  tables: TableNode[];
  joins: Join[];
  selectedFields: SelectedField[];
  where: WhereCondition | NotCondition | WhereClause | null;
  having?: WhereCondition | NotCondition | WhereClause | null;
  aggregations: Aggregation[];
  orderBy?: OrderByField[];
  limit: number;
  offset?: number;
  /** When set, LIMIT is bound to the declared template parameter. */
  limitParam?: string;
  /** When set, OFFSET is bound to the declared template parameter. */
  offsetParam?: string;
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
  sql?: string;
  params?: Record<string, any>;
}

export function isWhereCondition(node: WhereNode): node is WhereCondition {
  return 'op' in node && 'children' in node;
}

export function isNotCondition(node: WhereNode): node is NotCondition {
  return 'op' in node && node.op === 'NOT' && 'child' in node;
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
// Parameterised query templates
// ---------------------------------------------------------------------------
export type TemplateParamType =
  | 'string'
  | 'integer'
  | 'number'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'string_list'
  | 'integer_list'
  | 'number_list'
  | 'date_list';

export type TemplateParamUsage =
  | 'filter'
  | 'limit'
  | 'offset'
  | 'date_window_start'
  | 'date_window_end';

export interface TemplateParameter {
  name: string;
  type: TemplateParamType;
  label?: string;
  required?: boolean;
  default?: any;
  usage?: TemplateParamUsage;
  tableId?: string;
  columnName?: string;
  options?: { label: string; value: any }[];
  help?: string;
}

export interface TemplateDefinition {
  template_version: number;
  name: string;
  description?: string;
  parameters: TemplateParameter[];
  queryStructure: QueryStructure;
}

export interface QueryTemplate {
  id: number;
  name: string;
  description: string;
  template_version: number;
  template_definition: TemplateDefinition;
  share_token?: string;
  share_expires_at?: string;
  share_access_count: number;
  created_at: string;
  updated_at: string;
}

export interface TemplateInstantiateResult {
  sql: string;
  params: Record<string, any>;
  resolvedParameters: Record<string, any>;
  rows?: any[][];
  columns?: ResultColumn[];
  rowCount?: number;
  executionTime?: number;
}

// ---------------------------------------------------------------------------
// Batch parameter runs
// ---------------------------------------------------------------------------
export type BatchRunStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'failed';

export type BatchItemStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export interface BatchItem {
  id: number;
  itemIndex: number;
  status: BatchItemStatus;
  paramTypeSummary: { name: string; type: string; isNull: boolean }[];
  label?: string;
  executionId?: number;
  planFingerprint?: string;
  rowCount?: number;
  durationMs?: number;
  error?: string;
  resultPreview?: any[][];
  startedAt?: string;
  finishedAt?: string;
}

export interface BatchRun {
  id: number;
  idempotencyKey?: string;
  templateId: number;
  templateVersion: number;
  status: BatchRunStatus;
  concurrency: number;
  maxTotalRows?: number;
  timeoutSeconds?: number;
  totalItems: number;
  succeededItems: number;
  failedItems: number;
  cancelledItems: number;
  totalRows: number;
  error?: string;
  createdAt?: string;
  startedAt?: string;
  finishedAt?: string;
  items?: BatchItem[];
}

export interface BatchCreateRequest {
  templateId: number;
  parameterSets: Record<string, any>[];
  concurrency?: number;
  maxTotalRows?: number;
  timeoutSeconds?: number;
  idempotencyKey?: string;
  labels?: string[];
}
