import { useState, useEffect, useCallback } from 'react';
import { Code, Copy, Check, Play, Trash2, ChevronDown, RefreshCw, Plus } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import { debounce } from '@/lib/utils';
import { v4 as uuidv4 } from 'uuid';

export default function SQLPanel() {
  const [expanded, setExpanded] = useState(true);
  const [copied, setCopied] = useState(false);
  const generatedSQL = useQueryStore((state) => state.generatedSQL);
  const isGenerating = useQueryStore((state) => state.isGenerating);
  const isExecuting = useQueryStore((state) => state.isExecuting);
  const error = useQueryStore((state) => state.error);
  const generateSQL = useQueryStore((state) => state.generateSQL);
  const executeQuery = useQueryStore((state) => state.executeQuery);
  const clearAll = useQueryStore((state) => state.clearAll);
  const tables = useQueryStore((state) => state.tables);
  const addCTE = useQueryStore((state) => state.addCTE);
  const ctes = useQueryStore((state) => state.ctes);
  const getQueryStructure = useQueryStore((state) => state.getQueryStructure);

  const debouncedGenerate = useCallback(
    debounce(() => {
      generateSQL();
    }, 300),
    [generateSQL]
  );

  useEffect(() => {
    if (tables.length > 0) {
      debouncedGenerate();
    }
  }, [tables, debouncedGenerate]);

  const handleCopy = async () => {
    if (generatedSQL?.sql) {
      await navigator.clipboard.writeText(generatedSQL.sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleAddCTE = () => {
    const newCTE = {
      id: uuidv4(),
      name: `cte_${ctes.length + 1}`,
      queryStructure: getQueryStructure(),
    };
    addCTE(newCTE);
  };

  const formatSQL = (sql: string) => {
    return sql
      .replace(/\b(SELECT|FROM|WHERE|AND|OR|GROUP BY|ORDER BY|LIMIT|INNER|LEFT|RIGHT|FULL|JOIN|ON)\b/g, '\n$1')
      .replace(/\n{2,}/g, '\n')
      .trim();
  };

  return (
    <div className="border-t border-dark-700">
      <div className="w-full flex items-center justify-between p-4 hover:bg-dark-800/50 transition-colors">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-2 hover:text-primary-400 transition-colors"
          >
            <Code className="w-4 h-4 text-emerald-400" />
            <span className="font-medium text-dark-200">Generated SQL</span>
            {isGenerating && (
              <RefreshCw className="w-3.5 h-3.5 text-primary-400 animate-spin" />
            )}
            <ChevronDown
              className={`w-4 h-4 text-dark-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
            />
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleAddCTE}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-dark-700 hover:bg-dark-600 text-dark-300 rounded transition-colors"
            title="Add CTE from current canvas"
          >
            <Plus className="w-3.5 h-3.5" />
            Add CTE
          </button>
          <button
            onClick={() => generateSQL()}
            className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-700"
            title="Refresh SQL"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleCopy}
            disabled={!generatedSQL?.sql}
            className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-700 disabled:opacity-50"
            title="Copy SQL"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={() => executeQuery()}
            disabled={!generatedSQL?.sql || isExecuting}
            className="flex items-center gap-1.5 px-3 py-1 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isExecuting ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            {isExecuting ? 'Executing...' : 'Execute'}
          </button>
          <button
            onClick={() => clearAll()}
            className="p-1.5 text-dark-400 hover:text-red-400 transition-colors rounded hover:bg-dark-700"
            title="Clear all"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      {expanded && (
        <div className="px-4 pb-4">
          {error && (
            <div className="mb-3 p-3 bg-red-900/20 border border-red-800 rounded text-sm text-red-300">
              {error}
            </div>
          )}
          {generatedSQL?.sql ? (
            <div className="relative">
              <pre className="p-4 bg-dark-900 rounded-lg overflow-x-auto text-sm font-mono text-dark-200 max-h-[300px] overflow-y-auto">
                <code>
                  {formatSQL(generatedSQL.sql).split('\n').map((line, i) => (
                    <div key={i} className="flex">
                      <span className="w-8 text-right text-dark-600 mr-3 select-none">
                        {i + 1}
                      </span>
                      <span>{line}</span>
                    </div>
                  ))}
                </code>
              </pre>
              {Object.keys(generatedSQL.params).length > 0 && (
                <div className="mt-2 p-3 bg-dark-800 rounded border border-dark-700">
                  <div className="text-xs text-dark-400 mb-1">Parameters:</div>
                  <code className="text-xs text-dark-300 font-mono">
                    {JSON.stringify(generatedSQL.params, null, 2)}
                  </code>
                </div>
              )}
            </div>
          ) : (
            <div className="p-4 bg-dark-800 rounded-lg text-center text-dark-500 text-sm">
              {tables.length === 0
                ? 'Add tables to canvas to generate SQL'
                : isGenerating
                ? 'Generating SQL...'
                : 'No SQL generated yet'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
