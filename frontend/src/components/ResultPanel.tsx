import { useState } from 'react';
import { Table, ChevronDown, Clock, Database, X } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';

export default function ResultPanel() {
  const [expanded, setExpanded] = useState(true);
  const queryResult = useQueryStore((state) => state.queryResult);
  const clearResult = useQueryStore.setState;

  const getTypeColor = (type: string) => {
    const t = type.toUpperCase();
    if (t.includes('INT') || t === 'INTEGER') return 'bg-blue-900/50 text-blue-300';
    if (t.includes('DECIMAL') || t.includes('NUMERIC') || t.includes('FLOAT')) return 'bg-emerald-900/50 text-emerald-300';
    if (t.includes('CHAR') || t === 'STRING' || t === 'TEXT') return 'bg-amber-900/50 text-amber-300';
    if (t.includes('DATE') || t.includes('TIME')) return 'bg-purple-900/50 text-purple-300';
    if (t.includes('BOOL')) return 'bg-pink-900/50 text-pink-300';
    return 'bg-dark-600 text-dark-300';
  };

  const formatValue = (value: any) => {
    if (value === null || value === undefined) {
      return <span className="text-dark-500 italic">NULL</span>;
    }
    if (typeof value === 'boolean') {
      return value ? 'TRUE' : 'FALSE';
    }
    return String(value);
  };

  return (
    <div className="border-t border-dark-700 flex-1 flex flex-col min-h-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-dark-800/50 transition-colors flex-shrink-0"
      >
        <div className="flex items-center gap-2">
          <Table className="w-4 h-4 text-amber-400" />
          <span className="font-medium text-dark-200">Query Results</span>
          {queryResult && (
            <span className="text-xs bg-emerald-900/50 text-emerald-300 px-2 py-0.5 rounded">
              {queryResult.rowCount} rows
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {queryResult && (
            <>
              <div className="flex items-center gap-1 text-xs text-dark-400">
                <Clock className="w-3.5 h-3.5" />
                {queryResult.executionTime} ms
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  useQueryStore.setState({ queryResult: null });
                }}
                className="p-1 text-dark-500 hover:text-red-400 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </>
          )}
          <ChevronDown
            className={`w-4 h-4 text-dark-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </div>
      </button>
      {expanded && (
        <div className="flex-1 overflow-hidden px-4 pb-4 min-h-0">
          {queryResult ? (
            <div className="h-full flex flex-col min-h-0">
              <div className="mb-2 flex items-center gap-2">
                <Database className="w-3.5 h-3.5 text-dark-500" />
                <span className="text-xs text-dark-400">
                  {queryResult.columns.length} columns returned
                </span>
              </div>
              <div className="flex-1 overflow-auto bg-dark-800 rounded-lg border border-dark-700">
                <table className="w-full text-sm">
                  <thead className="bg-dark-700 sticky top-0">
                    <tr>
                      {queryResult.columns.map((col, i) => (
                        <th
                          key={i}
                          className="px-3 py-2 text-left font-medium text-dark-200 border-b border-dark-600 whitespace-nowrap"
                        >
                          <div className="flex items-center gap-2">
                            <span>{col.name}</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded ${getTypeColor(col.type)}`}>
                              {col.type}
                            </span>
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {queryResult.rows.map((row, rowIndex) => (
                      <tr
                        key={rowIndex}
                        className={`border-b border-dark-700/50 ${
                          rowIndex % 2 === 0 ? 'bg-dark-800' : 'bg-dark-800/50'
                        } hover:bg-dark-700/50 transition-colors`}
                      >
                        {row.map((cell, cellIndex) => (
                          <td
                            key={cellIndex}
                            className="px-3 py-2 text-dark-300 whitespace-nowrap font-mono text-xs"
                          >
                            {formatValue(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {queryResult.rows.length === 0 && (
                  <div className="p-8 text-center text-dark-500">
                    No rows returned
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center bg-dark-800 rounded-lg border border-dark-700 text-dark-500 text-sm">
              Execute a query to see results here
            </div>
          )}
        </div>
      )}
    </div>
  );
}
