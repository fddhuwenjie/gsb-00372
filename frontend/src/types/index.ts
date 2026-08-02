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

export type JoinType = 'INNER' | 'LEFT' | 'CROSS' | 'RIGHT' | 'FULL';

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
  | 'LIKE' | 'NOT LIKE'
  | 'IN' | 'NOT IN'
  | 'IS NULL' | 'IS NOT NULL'
  | 'EXISTS' | 'NOT EXISTS';

export interface WhereClause {
  tableId: string;
  columnName: string;
  cmp: ComparisonOperator;
  value?: string | number | boolean | (string | number)[];
  id: string;
  /** Optional aggregate wrapper, used for HAVING leaves (e.g. SUM). */
  function?: AggregationFunction;
  subquery?: QueryStructure;
}

export type LogicalOperator = 'AND' | 'OR' | 'NOT';

export interface WhereCondition {
  op: LogicalOperator;
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

export type SortDirection = 'ASC' | 'DESC';

export interface OrderByField {
  tableId: string;
  columnName: string;
  direction: SortDirection;
  function?: AggregationFunction;
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
  orderBy?: OrderByField[];
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

// --- Reusable parameterized templates --------------------------------------
export type ParamType = 'integer' | 'number' | 'string' | 'boolean' | 'date' | 'list';

export interface TemplateParameter {
  name: string;
  type: ParamType;
  required?: boolean;
  default?: any;
  label?: string;
  /** Element type for list parameters (e.g. IN lists). */
  itemType?: ParamType;
}

/** A placeholder that stands in for a parameter value inside a template AST. */
export interface ParamRef {
  $param: string;
}

export interface TemplateVersion {
  id: number;
  template_id: number;
  version: number;
  query_structure: QueryStructure;
  parameters: TemplateParameter[];
  created_at: string;
}

export interface QueryTemplate {
  id: number;
  name: string;
  description: string;
  query_structure: QueryStructure;
  parameters: TemplateParameter[];
  current_version: number;
  share_token?: string;
  share_expires_at?: string;
  share_access_count: number;
  created_at: string;
  updated_at: string;
  versions?: TemplateVersion[];
}

/** One reference produced by a schema-migration check. */
export interface SchemaMigrationRef {
  tableInstanceId: string | null;
  tableName: string | null;
  columnName: string | null;
  reason: string;
  message: string;
}

export type ParameterizeTarget =
  | { kind: 'filter'; clauseId: string }
  | { kind: 'limit' }
  | { kind: 'offset' };

export interface ParameterizeSpec {
  name: string;
  type: ParamType;
  required?: boolean;
  default?: any;
  label?: string;
  itemType?: ParamType;
  target: ParameterizeTarget;
}

export interface TemplateDefinition {
  queryStructure: QueryStructure;
  parameters: TemplateParameter[];
}

// --- Execution plan comparison ---------------------------------------------
export interface ParamTypeSummary {
  byName: Record<string, string>;
  histogram: Record<string, number>;
  count: number;
}

export interface PlanAccessNode {
  astNodeKind: 'access';
  tableRef: string | null;
  alias: string | null;
  access: 'scan' | 'search';
  index: string | null;
  automaticIndex: boolean;
  isFullScan: boolean;
}

export interface NormalizedPlan {
  accesses: PlanAccessNode[];
  usesTempBTreeForOrderBy: boolean;
  usesTempBTreeForGroupBy: boolean;
  usesTempBTreeForDistinct: boolean;
  usesSubquery: boolean;
}

export interface ExecutionPlanRecord {
  id: number;
  template_id: number | null;
  template_version: number | null;
  ast_hash: string;
  canonical_ast: any;
  param_type_summary: ParamTypeSummary;
  normalized_plan: NormalizedPlan;
  raw_plan: any[];
  duration_ms: number | null;
  row_count: number | null;
  created_at: string;
}

/** A single located change between two versions. `kind` names the AST node
 *  category (join/filter/aggregation/field/orderBy/access/planFlag). */
export interface PlanChange {
  kind: 'join' | 'filter' | 'aggregation' | 'field' | 'orderBy' | 'access' | 'planFlag';
  change: 'added' | 'removed' | 'modified';
  node?: any;
  from?: any;
  to?: any;
  tableRef?: string;
  flag?: string;
}

export interface PlanComparison {
  versionA: number;
  versionB: number;
  astHashA: string;
  astHashB: string;
  semanticallyEqual: boolean;
  astChanges: PlanChange[];
  planChanges: PlanChange[];
  paramTypeSummaryA: ParamTypeSummary;
  paramTypeSummaryB: ParamTypeSummary;
  result: {
    rowCountA: number | null;
    rowCountB: number | null;
    rowCountDelta: number | null;
    durationMsA: number | null;
    durationMsB: number | null;
    durationMsDelta: number | null;
  };
  changeCount: number;
}

export type TabType = 'result' | 'saved' | 'history' | 'plan' | 'share' | 'templates';
export type ResultViewMode = 'table' | 'chart';

// --- Cancellable batch parameter runs --------------------------------------
export type BatchStatus = 'pending' | 'running' | 'completed' | 'cancelled' | 'failed';
export type BatchItemStatus =
  | 'pending' | 'running' | 'succeeded' | 'failed' | 'rejected' | 'cancelled';

export interface BatchRunItem {
  id: number;
  batch_id: number;
  item_index: number;
  status: BatchItemStatus;
  param_type_summary: ParamTypeSummary | null;
  plan_record_id: number | null;
  row_count: number | null;
  duration_ms: number | null;
  error: string | null;
  attempts: number;
  updated_at: string | null;
}

export interface BatchRun {
  id: number;
  template_id: number;
  template_version: number;
  idempotency_key: string | null;
  status: BatchStatus;
  max_concurrency: number;
  max_total_rows: number | null;
  max_total_ms: number | null;
  per_item_timeout_ms: number;
  per_item_max_rows: number;
  total_rows: number;
  cancel_requested: boolean;
  counts: Record<BatchItemStatus, number>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  items?: BatchRunItem[];
}
