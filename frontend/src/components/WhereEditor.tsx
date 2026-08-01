import { useState } from 'react';
import { Plus, Trash2, Filter, ChevronDown } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { 
  WhereCondition, WhereClause, ComparisonOperator, 
  WhereNode, TableNode 
} from '@/types';
import { isWhereCondition, isWhereClause } from '@/types';

const OPERATORS: ComparisonOperator[] = ['=', '!=', '>', '<', '>=', '<=', 'LIKE', 'IN', 'NOT IN', 'EXISTS', 'NOT EXISTS'];
const SUBQUERY_OPERATORS: ComparisonOperator[] = ['IN', 'NOT IN', 'EXISTS', 'NOT EXISTS'];

function generateId(): string {
  return Math.random().toString(36).substring(2, 11);
}

interface WhereNodeEditorProps {
  node: WhereNode;
  path: number[];
  tables: TableNode[];
  onUpdate: (path: number[], node: WhereNode) => void;
  onRemove: (path: number[]) => void;
}

function WhereNodeEditor({ node, path, tables, onUpdate, onRemove }: WhereNodeEditorProps) {
  const metadata = useQueryStore((state) => state.metadata);

  const getAvailableColumns = () => {
    const columns: { tableId: string; tableName: string; columnName: string; columnType: string }[] = [];
    for (const table of tables) {
      const meta = metadata.find((m) => m.name === table.tableName);
      if (meta) {
        for (const col of meta.columns) {
          columns.push({
            tableId: table.id,
            tableName: table.tableName,
            columnName: col.name,
            columnType: col.type,
          });
        }
      }
    }
    return columns;
  };

  if (isWhereCondition(node)) {
    return (
      <div className="ml-4 border-l-2 border-dark-600 pl-3 py-2">
        <div className="flex items-center gap-2 mb-2">
          <select
            value={node.op}
            onChange={(e) =>
              onUpdate(path, { ...node, op: e.target.value as 'AND' | 'OR' })
            }
            className="bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
          >
            <option value="AND">AND</option>
            <option value="OR">OR</option>
          </select>
          <span className="text-xs text-dark-400">Group</span>
          <button
            onClick={() => onRemove(path)}
            className="ml-auto p-1 text-dark-500 hover:text-red-400 transition-colors"
            title="Remove group"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="space-y-2">
          {node.children.map((child, index) => (
            <WhereNodeEditor
              key={child.id}
              node={child}
              path={[...path, index]}
              tables={tables}
              onUpdate={onUpdate}
              onRemove={onRemove}
            />
          ))}
        </div>
        <div className="flex gap-2 mt-2">
          <button
            onClick={() => {
              const newClause: WhereClause = {
                id: generateId(),
                tableId: tables[0]?.id || '',
                columnName: '',
                cmp: '=',
                value: '',
              };
              onUpdate(path, {
                ...node,
                children: [...node.children, newClause],
              });
            }}
            className="flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            Add condition
          </button>
          <button
            onClick={() => {
              const newGroup: WhereCondition = {
                id: generateId(),
                op: 'AND',
                children: [],
              };
              onUpdate(path, {
                ...node,
                children: [...node.children, newGroup],
              });
            }}
            className="flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            Add group
          </button>
        </div>
      </div>
    );
  }

  if (isWhereClause(node)) {
    const columns = getAvailableColumns();
    const selectedColumn = columns.find(
      (c) => c.tableId === node.tableId && c.columnName === node.columnName
    );
    const isSubqueryOp = SUBQUERY_OPERATORS.includes(node.cmp);
    const hasSubquery = node.subquery !== undefined;

    return (
      <div className="py-1">
        <div className="flex items-center gap-2">
          <select
            value={node.tableId}
            onChange={(e) => {
              const tableId = e.target.value;
              const table = tables.find((t) => t.id === tableId);
              const meta = metadata.find((m) => m.name === table?.tableName);
              const firstCol = meta?.columns[0]?.name || '';
              onUpdate(path, { ...node, tableId, columnName: firstCol });
            }}
            className="bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200 focus:outline-none focus:border-primary-500 max-w-[120px] truncate"
          >
            {tables.map((t) => (
              <option key={t.id} value={t.id}>
                {t.alias}
              </option>
            ))}
          </select>
          <select
            value={node.columnName}
            onChange={(e) => onUpdate(path, { ...node, columnName: e.target.value })}
            className="bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200 focus:outline-none focus:border-primary-500 max-w-[140px] truncate"
          >
            {columns
              .filter((c) => c.tableId === node.tableId)
              .map((c) => (
                <option key={c.columnName} value={c.columnName}>
                  {c.columnName}
                </option>
              ))}
          </select>
          <select
            value={node.cmp}
            onChange={(e) => {
              const newCmp = e.target.value as ComparisonOperator;
              const newNode = { ...node, cmp: newCmp };
              if (!SUBQUERY_OPERATORS.includes(newCmp)) {
                delete newNode.subquery;
              }
              onUpdate(path, newNode);
            }}
            className="bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
          >
            {OPERATORS.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
          {isSubqueryOp && (
            <button
              onClick={() => {
                const newNode = { ...node };
                if (hasSubquery) {
                  delete newNode.subquery;
                  newNode.value = '';
                } else {
                  newNode.subquery = {
                    tables: [],
                    selectedFields: [],
                    joins: [],
                    where: null,
                    aggregations: [],
                    limit: 100,
                  };
                  delete newNode.value;
                }
                onUpdate(path, newNode);
              }}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                hasSubquery
                  ? 'bg-emerald-600 text-white'
                  : 'bg-dark-700 text-dark-300 hover:bg-dark-600'
              }`}
            >
              {hasSubquery ? 'Edit Subquery' : 'Use Subquery'}
            </button>
          )}
          {!isSubqueryOp ? (
            <input
              type="text"
              value={String(node.value)}
              placeholder="value"
              onChange={(e) => {
                let value: string | number = e.target.value;
                if (selectedColumn && selectedColumn.columnType.toLowerCase().includes('int')) {
                  const num = parseInt(e.target.value, 10);
                  if (!isNaN(num)) {
                    value = num;
                  }
                } else if (selectedColumn && (selectedColumn.columnType.toLowerCase().includes('decimal') || selectedColumn.columnType.toLowerCase().includes('numeric'))) {
                  const num = parseFloat(e.target.value);
                  if (!isNaN(num)) {
                    value = num;
                  }
                }
                onUpdate(path, { ...node, value });
              }}
              className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200 focus:outline-none focus:border-primary-500 min-w-[120px]"
            />
          ) : hasSubquery ? (
            <span className="flex-1 text-xs text-emerald-400 font-mono bg-dark-900 px-2 py-1 rounded truncate">
              (SELECT ...) [Subquery]
            </span>
          ) : node.cmp === 'IN' || node.cmp === 'NOT IN' ? (
            <input
              type="text"
              value={Array.isArray(node.value) ? node.value.join(', ') : ''}
              placeholder="value1, value2, ..."
              onChange={(e) => {
                const values = e.target.value
                  .split(',')
                  .map((v) => v.trim())
                  .filter((v) => v);
                onUpdate(path, { ...node, value: values });
              }}
              className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200 focus:outline-none focus:border-primary-500 min-w-[120px]"
            />
          ) : (
            <span className="flex-1 text-xs text-dark-500">
              Click "Use Subquery" to define
            </span>
          )}
          <button
            onClick={() => onRemove(path)}
            className="p-1 text-dark-500 hover:text-red-400 transition-colors"
            title="Remove condition"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
        {hasSubquery && (
          <div className="ml-6 mt-2 p-3 bg-dark-900 rounded border border-dark-600">
            <div className="text-xs text-dark-400 mb-2">Subquery - Drag tables to canvas to define</div>
            <div className="text-xs text-dark-500">
              Subquery structure stored in query. Click "Load to Canvas" to edit.
            </div>
          </div>
        )}
      </div>
    );
  }

  return null;
}

export default function WhereEditor() {
  const [expanded, setExpanded] = useState(true);
  const where = useQueryStore((state) => state.where);
  const tables = useQueryStore((state) => state.tables);
  const setWhere = useQueryStore((state) => state.setWhere);

  const updateNode = (path: number[], newNode: WhereNode) => {
    if (!where) return;

    const updateRecursive = (node: WhereCondition, currentPath: number[]): WhereCondition => {
      if (currentPath.length === 0) {
        return newNode as WhereCondition;
      }

      const [index, ...rest] = currentPath;
      const child = node.children[index];

      if (rest.length === 0) {
        const newChildren = [...node.children];
        newChildren[index] = newNode;
        return { ...node, children: newChildren };
      }

      if (isWhereCondition(child)) {
        const newChildren = [...node.children];
        newChildren[index] = updateRecursive(child, rest);
        return { ...node, children: newChildren };
      }

      return node;
    };

    const result = updateRecursive(where, path);
    setWhere(result);
  };

  const removeNode = (path: number[]) => {
    if (!where) return;

    const removeRecursive = (
      node: WhereCondition,
      currentPath: number[]
    ): WhereCondition | null => {
      const [index, ...rest] = currentPath;

      if (rest.length === 0) {
        const newChildren = node.children.filter((_, i) => i !== index);
        if (newChildren.length === 0) {
          return null;
        }
        return { ...node, children: newChildren };
      }

      const child = node.children[index];
      if (isWhereCondition(child)) {
        const result = removeRecursive(child, rest);
        const newChildren = [...node.children];
        if (result === null) {
          newChildren.splice(index, 1);
        } else {
          newChildren[index] = result;
        }
        if (newChildren.length === 0) {
          return null;
        }
        return { ...node, children: newChildren };
      }

      return node;
    };

    const result = removeRecursive(where, path);
    setWhere(result);
  };

  const addFirstCondition = () => {
    if (tables.length === 0) return;
    
    const firstTable = tables[0];
    const metadata = useQueryStore.getState().metadata;
    const meta = metadata.find((m) => m.name === firstTable.tableName);
    const firstCol = meta?.columns[0]?.name || '';

    const newClause: WhereClause = {
      id: generateId(),
      tableId: firstTable.id,
      columnName: firstCol,
      cmp: '=',
      value: '',
    };

    const newCondition: WhereCondition = {
      id: generateId(),
      op: 'AND',
      children: [newClause],
    };

    setWhere(newCondition);
  };

  if (tables.length === 0) {
    return (
      <div className="border-t border-dark-700">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between p-4 hover:bg-dark-800/50 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-primary-400" />
            <span className="font-medium text-dark-200">WHERE Conditions</span>
          </div>
          <ChevronDown
            className={`w-4 h-4 text-dark-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
        {expanded && (
          <div className="px-4 pb-4">
            <p className="text-sm text-dark-500">Add tables to canvas to add conditions</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="border-t border-dark-700">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-dark-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-primary-400" />
          <span className="font-medium text-dark-200">WHERE Conditions</span>
          {where && (
            <span className="text-xs bg-primary-900/50 text-primary-300 px-2 py-0.5 rounded">
              Active
            </span>
          )}
        </div>
        <ChevronDown
          className={`w-4 h-4 text-dark-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>
      {expanded && (
        <div className="px-4 pb-4">
          {where ? (
            <WhereNodeEditor
              node={where}
              path={[]}
              tables={tables}
              onUpdate={updateNode}
              onRemove={removeNode}
            />
          ) : (
            <button
              onClick={addFirstCondition}
              className="flex items-center gap-2 text-sm text-primary-400 hover:text-primary-300 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Add first condition
            </button>
          )}
        </div>
      )}
    </div>
  );
}
