import { useState } from 'react';
import { Plus, X, Edit2, Trash2, Code, ChevronDown, ChevronRight } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { CTE, QueryStructure } from '@/types';

function generateId() {
  return Math.random().toString(36).substring(2, 11);
}

export default function CTEPane() {
  const [expanded, setExpanded] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const ctes = useQueryStore((state) => state.ctes);
  const addCTE = useQueryStore((state) => state.addCTE);
  const removeCTE = useQueryStore((state) => state.removeCTE);
  const updateCTE = useQueryStore((state) => state.updateCTE);
  const loadQueryStructure = useQueryStore((state) => state.loadQueryStructure);
  const tables = useQueryStore((state) => state.tables);

  const handleAddCTE = () => {
    const newCTE: CTE = {
      id: generateId(),
      name: `cte_${ctes.length + 1}`,
      queryStructure: {
        tables: [],
        joins: [],
        selectedFields: [],
        where: null,
        aggregations: [],
        limit: 100,
      },
    };
    addCTE(newCTE);
    setEditingId(newCTE.id);
    setEditName(newCTE.name);
  };

  const handleEditCTE = (cte: CTE) => {
    setEditingId(cte.id);
    setEditName(cte.name);
  };

  const handleSaveEdit = (id: string) => {
    if (editName.trim()) {
      updateCTE(id, { name: editName.trim() });
    }
    setEditingId(null);
  };

  const handleLoadCTE = (cte: CTE) => {
    loadQueryStructure(cte.queryStructure);
  };

  const handleSaveCurrentAsCTE = () => {
    const structure: QueryStructure = {
      tables: useQueryStore.getState().tables,
      joins: useQueryStore.getState().joins,
      selectedFields: useQueryStore.getState().selectedFields,
      where: useQueryStore.getState().where,
      aggregations: useQueryStore.getState().aggregations,
      limit: useQueryStore.getState().limit,
      ctes: undefined,
    };

    const newCTE: CTE = {
      id: generateId(),
      name: `cte_${ctes.length + 1}`,
      queryStructure: structure,
    };
    addCTE(newCTE);
  };

  return (
    <div className="border-t border-dark-700">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-dark-800/50 transition-colors flex-shrink-0"
      >
        <div className="flex items-center gap-2">
          <Code className="w-4 h-4 text-cyan-400" />
          <span className="font-medium text-dark-200">CTEs ({ctes.length})</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleSaveCurrentAsCTE();
            }}
            disabled={tables.length === 0}
            className="text-xs px-2 py-1 bg-dark-700 hover:bg-dark-600 text-dark-200 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Save current canvas as CTE"
          >
            + Save as CTE
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleAddCTE();
            }}
            className="text-xs px-2 py-1 bg-cyan-600 hover:bg-cyan-500 text-white rounded transition-colors"
          >
            + Add CTE
          </button>
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-dark-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-dark-400" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-2">
          {ctes.length === 0 ? (
            <div className="text-center text-sm text-dark-500 py-4">
              No CTEs defined yet
            </div>
          ) : (
            ctes.map((cte) => (
              <div
                key={cte.id}
                className="flex items-center gap-2 p-2 bg-dark-800 rounded border border-dark-700"
              >
                {editingId === cte.id ? (
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onBlur={() => handleSaveEdit(cte.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSaveEdit(cte.id);
                      if (e.key === 'Escape') setEditingId(null);
                    }}
                    autoFocus
                    className="flex-1 px-2 py-1 bg-dark-900 border border-primary-500 rounded text-dark-100 text-sm focus:outline-none"
                  />
                ) : (
                  <code className="flex-1 text-sm text-cyan-300 font-mono truncate">
                    {cte.name}
                  </code>
                )}
                <button
                  onClick={() => handleLoadCTE(cte)}
                  className="p-1 text-dark-400 hover:text-primary-400 transition-colors"
                  title="Load to canvas"
                >
                  <Edit2 className="w-4 h-4" />
                </button>
                {editingId !== cte.id && (
                  <button
                    onClick={() => handleEditCTE(cte)}
                    className="p-1 text-dark-400 hover:text-dark-200 transition-colors"
                    title="Rename"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                )}
                <button
                  onClick={() => removeCTE(cte.id)}
                  className="p-1 text-dark-400 hover:text-red-400 transition-colors"
                  title="Delete"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
