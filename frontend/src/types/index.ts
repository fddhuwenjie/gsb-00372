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

export type JoinType = 'INNER' | 'LEFT' | 'RIGHT' | 'FULL';

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

export type ComparisonOperator = '=' | '!=' | '>' | '<' | '>=' | '<=' | 'LIKE' | 'IN' | 'NOT IN' | 'EXISTS' | 'NOT EXISTS';

export interface WhereClause {
  tableId: string;
  columnName: string;
  cmp: ComparisonOperator;
  value: string | number | boolean | (string | number)[];
  id: string;
  subquery?: QueryStructure;
}

export interface WhereCondition {
  op: 'AND' | 'OR';
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
  aggregations: Aggregation[];
  limit: number;
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

export type TabType = 'result' | 'saved' | 'history' | 'plan' | 'share';
export type ResultViewMode = 'table' | 'chart';
