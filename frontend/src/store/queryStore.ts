import { create } from 'zustand';
import { v4 as uuidv4 } from 'uuid';
import type { 
  TableMetadata, TableNode, Join, SelectedField, WhereCondition, 
  Aggregation, QueryStructure, QueryResult, GeneratedSQL, WhereClause,
  CTE, TabType, ResultViewMode, ChartConfig, SavedQuery, QueryHistoryItem, ExplainResult,
  QueryTemplate, TemplateParameter
} from '@/types';
import { 
  generateSQL, executeQuery, getSavedQueries, createSavedQuery, 
  updateSavedQuery, deleteSavedQuery, shareQuery, getQueryHistory,
  explainQuery, getTemplates, createTemplate, deleteTemplate, instantiateTemplate
} from '@/services/api';
import { deriveParameters } from '@/lib/templateParams';

/**
 * Create a new canvas table instance with a stable unique id and a
 * deterministic, collision-free alias. Self-joins of the same table get
 * distinct aliases (cu, cu2, ...), and prefixes shared by different tables
 * (order / order_item) are disambiguated the same way.
 */
export function createTableInstance(
  tableName: string,
  position: { x: number; y: number },
  existingTables: TableNode[]
): TableNode {
  const base = tableName.substring(0, 2).toLowerCase();
  const usedAliases = new Set(existingTables.map((t) => t.alias));
  let alias = base;
  let n = 2;
  while (usedAliases.has(alias)) {
    alias = `${base}${n}`;
    n += 1;
  }
  return {
    id: `node-${uuidv4().slice(0, 8)}`,
    tableName,
    alias,
    position,
  };
}

interface QueryState {
  metadata: TableMetadata[];
  tables: TableNode[];
  joins: Join[];
  selectedFields: SelectedField[];
  where: WhereCondition | null;
  having: WhereCondition | null;
  aggregations: Aggregation[];
  limit: number;
  offset: number;
  ctes: CTE[];
  generatedSQL: GeneratedSQL | null;
  queryResult: QueryResult | null;
  isExecuting: boolean;
  isGenerating: boolean;
  error: string | null;
  suggestedJoins: Join[];
  activeTab: TabType;
  resultViewMode: ResultViewMode;
  chartConfig: ChartConfig | null;
  savedQueries: SavedQuery[];
  queryHistory: QueryHistoryItem[];
  templates: QueryTemplate[];
  isLoadingTemplates: boolean;
  explainResult: ExplainResult | null;
  isExplaining: boolean;
  isLoadingSaved: boolean;
  isLoadingHistory: boolean;
  currentSavedId: number | null;
  
  setMetadata: (metadata: TableMetadata[]) => void;
  addTable: (table: TableNode) => void;
  removeTable: (tableId: string) => void;
  updateTablePosition: (tableId: string, position: { x: number; y: number }) => void;
  addJoin: (join: Join) => void;
  removeJoin: (joinId: string) => void;
  updateJoinType: (joinId: string, type: Join['type']) => void;
  toggleField: (tableId: string, columnName: string, selected: boolean) => void;
  setWhere: (where: WhereCondition | null) => void;
  setHaving: (having: WhereCondition | null) => void;
  addWhereClause: (clause: WhereClause) => void;
  removeWhereClause: (clauseId: string) => void;
  addAggregation: (agg: Aggregation) => void;
  removeAggregation: (tableId: string, columnName: string) => void;
  setLimit: (limit: number) => void;
  setOffset: (offset: number) => void;
  generateSQL: () => Promise<void>;
  executeQuery: () => Promise<void>;
  clearAll: () => void;
  updateSuggestedJoins: () => void;
  
  addCTE: (cte: CTE) => void;
  removeCTE: (cteId: string) => void;
  updateCTE: (cteId: string, cte: Partial<CTE>) => void;
  
  setActiveTab: (tab: TabType) => void;
  setResultViewMode: (mode: ResultViewMode) => void;
  setChartConfig: (config: ChartConfig | null) => void;
  
  loadSavedQueries: () => Promise<void>;
  saveQuery: (name: string, description?: string) => Promise<SavedQuery>;
  updateCurrentQuery: () => Promise<SavedQuery | null>;
  deleteQuery: (id: number) => Promise<void>;
  loadQuery: (query: SavedQuery) => void;
  shareCurrentQuery: (expiresInHours?: number) => Promise<{ token: string; url: string; expires_at?: string } | null>;
  
  loadQueryHistory: () => Promise<void>;
  replayHistory: (item: QueryHistoryItem) => void;
  
  runExplain: () => Promise<void>;
  
  loadQueryStructure: (structure: QueryStructure) => void;

  getQueryStructure: () => QueryStructure;

  loadTemplates: () => Promise<void>;
  saveAsTemplate: (name: string, description?: string) => Promise<QueryTemplate>;
  removeTemplate: (id: number) => Promise<void>;
  instantiateTemplate: (id: number, values: Record<string, unknown>) => Promise<void>;
}

function generateId(): string {
  return Math.random().toString(36).substring(2, 11);
}

/**
 * The one and only AST assembly point. The backend owns all SQL semantics;
 * the frontend only ships this structure.
 */
function buildQueryStructure(state: {
  tables: TableNode[];
  joins: Join[];
  selectedFields: SelectedField[];
  where: WhereCondition | null;
  having: WhereCondition | null;
  aggregations: Aggregation[];
  limit: number;
  offset: number;
  ctes: CTE[];
}): QueryStructure {
  return {
    tables: state.tables,
    joins: state.joins,
    selectedFields: state.selectedFields,
    where: state.where,
    having: state.having,
    aggregations: state.aggregations,
    limit: state.limit,
    offset: state.offset,
    ctes: state.ctes.length > 0 ? state.ctes : undefined,
  };
}

/**
 * Normalize an AST coming back from storage or a share link. Stable table
 * instance ids and aliases are preserved verbatim.
 */
function restoredState(structure: QueryStructure) {
  return {
    tables: structure.tables || [],
    joins: structure.joins || [],
    selectedFields: structure.selectedFields || [],
    where: structure.where || null,
    having: structure.having || null,
    aggregations: structure.aggregations || [],
    limit: structure.limit || 100,
    offset: structure.offset ?? 0,
    ctes: structure.ctes || [],
  };
}

function removeWhereNode(condition: WhereCondition, nodeId: string): WhereCondition | null {
  const newChildren = condition.children
    .map(child => {
      if ('id' in child && child.id === nodeId) {
        return null;
      }
      if ('op' in child && 'children' in child) {
        const result = removeWhereNode(child, nodeId);
        return result;
      }
      return child;
    })
    .filter((child): child is NonNullable<typeof child> => child !== null);

  if (newChildren.length === 0) {
    return null;
  }

  return {
    ...condition,
    children: newChildren,
  };
}

function calculateSuggestedJoins(
  metadata: TableMetadata[],
  tables: TableNode[],
  joins: Join[]
): Join[] {
  const suggested: Join[] = [];
  
  for (let i = 0; i < tables.length; i++) {
    for (let j = i + 1; j < tables.length; j++) {
      const table1 = tables[i];
      const table2 = tables[j];
      
      const meta1 = metadata.find(m => m.name === table1.tableName);
      const meta2 = metadata.find(m => m.name === table2.tableName);
      
      if (!meta1 || !meta2) continue;
      
      const checkFK = (
        fkMeta: TableMetadata,
        fkTable: TableNode,
        otherMeta: TableMetadata,
        otherTable: TableNode,
        reverse: boolean
      ) => {
        for (const fk of fkMeta.foreignKeys) {
          if (fk.toTable === otherMeta.name) {
            const exists = joins.some(
              j => (j.leftTableId === fkTable.id && j.rightTableId === otherTable.id && 
                    j.leftColumn === fk.fromColumn && j.rightColumn === fk.toColumn) ||
                     (j.leftTableId === otherTable.id && j.rightTableId === fkTable.id &&
                      j.leftColumn === fk.toColumn && j.rightColumn === fk.fromColumn)
            );
            if (!exists) {
              const joinId = `suggested-${fkTable.id}-${otherTable.id}-${fk.fromColumn}-${fk.toColumn}`;
              suggested.push({
                id: joinId,
                type: 'INNER',
                leftTableId: reverse ? otherTable.id : fkTable.id,
                leftColumn: reverse ? fk.toColumn : fk.fromColumn,
                rightTableId: reverse ? fkTable.id : otherTable.id,
                rightColumn: reverse ? fk.fromColumn : fk.toColumn,
                leftTable: reverse ? otherMeta.name : fkMeta.name,
                rightTable: reverse ? fkMeta.name : otherMeta.name,
              });
            }
          }
        }
      };
      
      checkFK(meta1, table1, meta2, table2, false);
      checkFK(meta2, table2, meta1, table1, true);
    }
  }
  
  return suggested;
}

export const useQueryStore = create<QueryState>((set, get) => ({
  metadata: [],
  tables: [],
  joins: [],
  selectedFields: [],
  where: null,
  having: null,
  aggregations: [],
  limit: 100,
  offset: 0,
  ctes: [],
  generatedSQL: null,
  queryResult: null,
  isExecuting: false,
  isGenerating: false,
  error: null,
  suggestedJoins: [],
  activeTab: 'result',
  resultViewMode: 'table',
  chartConfig: null,
  savedQueries: [],
  queryHistory: [],
  templates: [],
  isLoadingTemplates: false,
  explainResult: null,
  isExplaining: false,
  isLoadingSaved: false,
  isLoadingHistory: false,
  currentSavedId: null,

  updateSuggestedJoins: () => {
    const state = get();
    const suggested = calculateSuggestedJoins(state.metadata, state.tables, state.joins);
    set({ suggestedJoins: suggested });
  },

  setMetadata: (metadata) => {
    set({ metadata });
    get().updateSuggestedJoins();
  },

  addTable: (table) => {
    set((state) => ({
      tables: [...state.tables, table],
    }));
    get().updateSuggestedJoins();
  },

  removeTable: (tableId) => {
    set((state) => {
      const table = state.tables.find(t => t.id === tableId);
      if (!table) return {};

      return {
        tables: state.tables.filter(t => t.id !== tableId),
        joins: state.joins.filter(j => j.leftTableId !== tableId && j.rightTableId !== tableId),
        selectedFields: state.selectedFields.filter(f => f.tableId !== tableId),
        aggregations: state.aggregations.filter(a => a.tableId !== tableId),
      };
    });
    get().updateSuggestedJoins();
  },

  updateTablePosition: (tableId, position) => set((state) => ({
    tables: state.tables.map(t => 
      t.id === tableId ? { ...t, position } : t
    ),
  })),

  addJoin: (join) => {
    set((state) => ({
      joins: [...state.joins, join],
    }));
    get().updateSuggestedJoins();
  },

  removeJoin: (joinId) => {
    set((state) => ({
      joins: state.joins.filter(j => j.id !== joinId),
    }));
    get().updateSuggestedJoins();
  },

  updateJoinType: (joinId, type) => set((state) => ({
    joins: state.joins.map(j => 
      j.id === joinId ? { ...j, type } : j
    ),
  })),

  toggleField: (tableId, columnName, selected) => set((state) => {
    if (selected) {
      return {
        selectedFields: [...state.selectedFields, { tableId, columnName }],
      };
    } else {
      return {
        selectedFields: state.selectedFields.filter(
          f => !(f.tableId === tableId && f.columnName === columnName)
        ),
        aggregations: state.aggregations.filter(
          a => !(a.tableId === tableId && a.columnName === columnName)
        ),
      };
    }
  }),

  setWhere: (where) => set({ where }),

  setHaving: (having) => set({ having }),

  addWhereClause: (clause) => set((state) => {
    if (!state.where) {
      return {
        where: {
          id: generateId(),
          op: 'AND',
          children: [clause],
        },
      };
    }

    const addToCondition = (cond: WhereCondition): WhereCondition => {
      if (cond.children.length === 0 || !('op' in cond.children[0])) {
        return {
          ...cond,
          children: [...cond.children, clause],
        };
      }
      return cond;
    };

    return {
      where: addToCondition(state.where),
    };
  }),

  removeWhereClause: (clauseId) => set((state) => {
    if (!state.where) return {};
    const result = removeWhereNode(state.where, clauseId);
    return { where: result };
  }),

  addAggregation: (agg) => set((state) => {
    const exists = state.aggregations.find(
      a => a.tableId === agg.tableId && a.columnName === agg.columnName
    );
    if (exists) {
      return {
        aggregations: state.aggregations.map(a =>
          a.tableId === agg.tableId && a.columnName === agg.columnName ? agg : a
        ),
      };
    }
    return {
      aggregations: [...state.aggregations, agg],
    };
  }),

  removeAggregation: (tableId, columnName) => set((state) => ({
    aggregations: state.aggregations.filter(
      a => !(a.tableId === tableId && a.columnName === columnName)
    ),
  })),

  setLimit: (limit) => set({ limit }),

  setOffset: (offset) => set({ offset }),

  generateSQL: async () => {
    const state = get();
    if (state.tables.length === 0) {
      set({ generatedSQL: null, error: null });
      return;
    }

    set({ isGenerating: true, error: null });
    try {
      const result = await generateSQL(buildQueryStructure(state));
      set({ generatedSQL: result, isGenerating: false });
    } catch (err) {
      set({ 
        error: err instanceof Error ? err.message : 'Failed to generate SQL', 
        isGenerating: false,
        generatedSQL: null,
      });
    }
  },

  executeQuery: async () => {
    const state = get();
    if (state.tables.length === 0) {
      set({ error: 'Please add at least one table' });
      return;
    }

    set({ isExecuting: true, error: null });
    try {
      const result = await executeQuery(buildQueryStructure(state));
      set({ queryResult: result, isExecuting: false });
    } catch (err) {
      set({ 
        error: err instanceof Error ? err.message : 'Failed to execute query', 
        isExecuting: false,
        queryResult: null,
      });
    }
  },

  clearAll: () => {
    set({
      tables: [],
      joins: [],
      selectedFields: [],
      where: null,
      having: null,
      aggregations: [],
      limit: 100,
      offset: 0,
      ctes: [],
      generatedSQL: null,
      queryResult: null,
      error: null,
      suggestedJoins: [],
      chartConfig: null,
      currentSavedId: null,
      explainResult: null,
    });
  },

  addCTE: (cte) => {
    set((state) => ({
      ctes: [...state.ctes, cte],
    }));
  },

  removeCTE: (cteId) => {
    set((state) => ({
      ctes: state.ctes.filter((c) => c.id !== cteId),
    }));
  },

  updateCTE: (cteId, updates) => {
    set((state) => ({
      ctes: state.ctes.map((c) =>
        c.id === cteId ? { ...c, ...updates } : c
      ),
    }));
  },

  setActiveTab: (tab) => {
    set({ activeTab: tab });
  },

  setResultViewMode: (mode) => {
    set({ resultViewMode: mode });
  },

  setChartConfig: (config) => {
    set({ chartConfig: config });
  },

  loadSavedQueries: async () => {
    set({ isLoadingSaved: true });
    try {
      const queries = await getSavedQueries();
      set({ savedQueries: queries, isLoadingSaved: false });
    } catch (err) {
      set({ 
        error: err instanceof Error ? err.message : 'Failed to load saved queries',
        isLoadingSaved: false,
      });
    }
  },

  saveQuery: async (name, description) => {
    const state = get();
    const saved = await createSavedQuery({
      name,
      description,
      query_structure: buildQueryStructure(state),
      chart_config: state.chartConfig || undefined,
    });
    set({ currentSavedId: saved.id });
    get().loadSavedQueries();
    return saved;
  },

  updateCurrentQuery: async () => {
    const state = get();
    if (!state.currentSavedId) return null;
    
    const updated = await updateSavedQuery(state.currentSavedId, {
      query_structure: buildQueryStructure(state),
      chart_config: state.chartConfig || undefined,
    });
    get().loadSavedQueries();
    return updated;
  },

  deleteQuery: async (id) => {
    await deleteSavedQuery(id);
    if (get().currentSavedId === id) {
      set({ currentSavedId: null });
    }
    get().loadSavedQueries();
  },

  loadQuery: (query) => {
    set({
      ...restoredState(query.query_structure),
      chartConfig: query.chart_config || null,
      currentSavedId: query.id,
      queryResult: null,
      generatedSQL: null,
    });
    get().updateSuggestedJoins();
  },

  shareCurrentQuery: async (expiresInHours) => {
    const state = get();
    if (!state.currentSavedId) return null;
    return await shareQuery(state.currentSavedId, expiresInHours);
  },

  loadQueryHistory: async () => {
    set({ isLoadingHistory: true });
    try {
      const history = await getQueryHistory();
      set({ queryHistory: history, isLoadingHistory: false });
    } catch (err) {
      set({ 
        error: err instanceof Error ? err.message : 'Failed to load query history',
        isLoadingHistory: false,
      });
    }
  },

  replayHistory: (item) => {
    set({
      ...restoredState(item.query_structure),
      currentSavedId: null,
      queryResult: null,
      generatedSQL: null,
      activeTab: 'result',
    });
    get().updateSuggestedJoins();
  },

  runExplain: async () => {
    const state = get();
    if (state.tables.length === 0) {
      set({ error: 'Please add at least one table' });
      return;
    }

    set({ isExplaining: true, error: null });
    try {
      const result = await explainQuery(buildQueryStructure(state));
      set({ explainResult: result, isExplaining: false, activeTab: 'plan' });
    } catch (err) {
      set({ 
        error: err instanceof Error ? err.message : 'Failed to explain query', 
        isExplaining: false,
      });
    }
  },

  loadQueryStructure: (structure) => {
    set({
      ...restoredState(structure),
      currentSavedId: null,
      queryResult: null,
      generatedSQL: null,
    });
    get().updateSuggestedJoins();
  },

  getQueryStructure: () => {
    return buildQueryStructure(get());
  },

  loadTemplates: async () => {
    set({ isLoadingTemplates: true });
    try {
      const templates = await getTemplates();
      set({ templates, isLoadingTemplates: false });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to load templates',
        isLoadingTemplates: false,
      });
    }
  },

  saveAsTemplate: async (name, description) => {
    const state = get();
    const structure = buildQueryStructure(state);
    const parameters: TemplateParameter[] = deriveParameters(structure, state.metadata);
    const template = await createTemplate({
      name,
      description,
      parameters,
      query_structure: structure,
    });
    get().loadTemplates();
    return template;
  },

  removeTemplate: async (id) => {
    await deleteTemplate(id);
    get().loadTemplates();
  },

  instantiateTemplate: async (id, values) => {
    // Instantiation happens entirely on the backend; the returned AST is
    // loaded onto the canvas and its executed result is displayed.
    const result = await instantiateTemplate(id, values, true);
    get().loadQueryStructure(result.query_structure);
    set({
      queryResult: result.result ?? null,
      generatedSQL: { sql: result.sql, params: result.params },
      currentSavedId: null,
      activeTab: 'result',
      error: null,
    });
  },
}));
