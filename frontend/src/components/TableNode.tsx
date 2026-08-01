import { Handle, Position, useReactFlow } from 'reactflow';
import { X, Key, Hash, FunctionSquare } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { TableMetadata, AggregationFunction } from '@/types';

interface TableNodeProps {
  data: {
    tableName: string;
    alias: string;
  };
  id: string;
}

const AGG_FUNCTIONS: AggregationFunction[] = ['SUM', 'AVG', 'COUNT', 'MAX', 'MIN'];

export default function TableNode({ data, id }: TableNodeProps) {
  const { setNodes } = useReactFlow();
  const metadata = useQueryStore((state) => state.metadata);
  const selectedFields = useQueryStore((state) => state.selectedFields);
  const aggregations = useQueryStore((state) => state.aggregations);
  const toggleField = useQueryStore((state) => state.toggleField);
  const removeTable = useQueryStore((state) => state.removeTable);
  const addAggregation = useQueryStore((state) => state.addAggregation);
  const removeAggregation = useQueryStore((state) => state.removeAggregation);

  const tableMeta = metadata.find((m) => m.name === data.tableName);
  if (!tableMeta) return null;

  const isFieldSelected = (columnName: string) =>
    selectedFields.some((f) => f.tableId === id && f.columnName === columnName);

  const getFieldAggregation = (columnName: string) =>
    aggregations.find(
      (a) => a.tableId === id && a.columnName === columnName
    );

  const handleRemove = () => {
    removeTable(id);
    setNodes((nodes) => nodes.filter((n) => n.id !== id));
  };

  const handleToggleField = (columnName: string, selected: boolean) => {
    toggleField(id, columnName, selected);
  };

  const handleAggregationChange = (columnName: string, func: AggregationFunction | null) => {
    if (func) {
      addAggregation({
        tableId: id,
        columnName,
        function: func,
      });
    } else {
      removeAggregation(id, columnName);
    }
  };

  const isNumericColumn = (type: string) => {
    const t = type.toLowerCase();
    return t.includes('int') || t.includes('decimal') || t.includes('numeric') || t.includes('float') || t.includes('real');
  };

  return (
    <div className="min-w-[240px] bg-dark-800 border border-dark-600 rounded-lg shadow-xl overflow-hidden">
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-primary-500 !border-2 !border-dark-800"
      />
      <Handle
        type="source"
        position={Position.Top}
        className="!w-3 !h-3 !bg-primary-500 !border-2 !border-dark-800"
      />

      <div className="flex items-center justify-between px-3 py-2 bg-dark-700 border-b border-dark-600">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-primary-400">{data.alias}</span>
          <span className="text-xs text-dark-400">({data.tableName})</span>
        </div>
        <button
          onClick={handleRemove}
          className="p-1 hover:bg-dark-600 rounded text-dark-400 hover:text-red-400 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="py-1 max-h-[300px] overflow-y-auto">
        {tableMeta.columns.map((col) => {
          const selected = isFieldSelected(col.name);
          const agg = getFieldAggregation(col.name);
          const numeric = isNumericColumn(col.type);

          return (
            <div
              key={col.name}
              className={`flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-dark-700/50 transition-colors ${
                selected ? 'bg-dark-700/30' : ''
              }`}
            >
              <input
                type="checkbox"
                checked={selected}
                onChange={(e) => handleToggleField(col.name, e.target.checked)}
                className="w-4 h-4 rounded border-dark-500 bg-dark-700 text-primary-500 focus:ring-primary-500 focus:ring-offset-dark-800"
              />
              {col.isPrimaryKey ? (
                <Key className="w-3.5 h-3.5 text-yellow-500 flex-shrink-0" />
              ) : (
                <Hash className="w-3.5 h-3.5 text-dark-500 flex-shrink-0" />
              )}
              <span className={`flex-1 min-w-0 truncate ${selected ? 'text-dark-100' : 'text-dark-300'}`}>
                {col.name}
              </span>
              <span className="text-xs text-dark-500 flex-shrink-0">{col.type}</span>
              
              {selected && numeric && (
                <div className="flex items-center">
                  <select
                    value={agg?.function || ''}
                    onChange={(e) =>
                      handleAggregationChange(
                        col.name,
                        (e.target.value as AggregationFunction) || null
                      )
                    }
                    className="ml-1 text-xs bg-dark-700 border border-dark-600 rounded px-1.5 py-0.5 text-dark-300 focus:outline-none focus:border-primary-500"
                  >
                    <option value="">None</option>
                    {AGG_FUNCTIONS.map((fn) => (
                      <option key={fn} value={fn}>
                        {fn}
                      </option>
                    ))}
                  </select>
                  {agg && (
                    <FunctionSquare className="w-3.5 h-3.5 text-emerald-400 ml-1" />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
