import { useState } from 'react';
import { Link, ChevronDown, Trash2, Plus, Lightbulb } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { JoinType } from '@/types';

const JOIN_TYPES: JoinType[] = ['INNER', 'LEFT', 'RIGHT', 'FULL'];

export default function JoinEditor() {
  const [expanded, setExpanded] = useState(true);
  const joins = useQueryStore((state) => state.joins);
  const suggestedJoins = useQueryStore((state) => state.suggestedJoins);
  const removeJoin = useQueryStore((state) => state.removeJoin);
  const updateJoinType = useQueryStore((state) => state.updateJoinType);
  const addJoin = useQueryStore((state) => state.addJoin);
  const tables = useQueryStore((state) => state.tables);

  const getJoinDescription = (type: JoinType) => {
    switch (type) {
      case 'INNER':
        return 'Returns rows where both tables have matching values';
      case 'LEFT':
        return 'Returns all rows from left table, matching from right';
      case 'RIGHT':
        return 'Returns all rows from right table, matching from left';
      case 'FULL':
        return 'Returns all rows from both tables';
    }
  };

  const getJoinColor = (type: JoinType) => {
    switch (type) {
      case 'INNER':
        return 'bg-primary-900/50 text-primary-300 border-primary-700';
      case 'LEFT':
        return 'bg-emerald-900/50 text-emerald-300 border-emerald-700';
      case 'RIGHT':
        return 'bg-amber-900/50 text-amber-300 border-amber-700';
      case 'FULL':
        return 'bg-purple-900/50 text-purple-300 border-purple-700';
    }
  };

  const getTableAlias = (tableId: string) => {
    const table = tables.find((t) => t.id === tableId);
    return table?.alias || tableId;
  };

  if (tables.length < 2) {
    return (
      <div className="border-t border-dark-700">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between p-4 hover:bg-dark-800/50 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Link className="w-4 h-4 text-primary-400" />
            <span className="font-medium text-dark-200">JOINs</span>
          </div>
          <ChevronDown
            className={`w-4 h-4 text-dark-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
        {expanded && (
          <div className="px-4 pb-4">
            <p className="text-sm text-dark-500">Add at least two tables to create JOINs</p>
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
          <Link className="w-4 h-4 text-primary-400" />
          <span className="font-medium text-dark-200">JOINs</span>
          {joins.length > 0 && (
            <span className="text-xs bg-primary-900/50 text-primary-300 px-2 py-0.5 rounded">
              {joins.length} active
            </span>
          )}
          {suggestedJoins.length > 0 && (
            <span className="text-xs bg-amber-900/50 text-amber-300 px-2 py-0.5 rounded">
              {suggestedJoins.length} suggested
            </span>
          )}
        </div>
        <ChevronDown
          className={`w-4 h-4 text-dark-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>
      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {suggestedJoins.length > 0 && (
            <div className="p-3 bg-amber-900/20 border border-amber-800/50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Lightbulb className="w-4 h-4 text-amber-400" />
                <span className="text-sm font-medium text-amber-300">Suggested JOINs</span>
                <span className="text-xs text-amber-500">
                  (based on foreign key relationships)
                </span>
              </div>
              <div className="space-y-2">
                {suggestedJoins.map((join) => (
                  <div
                    key={join.id}
                    className="flex items-center gap-2 p-2 bg-dark-800 rounded border border-dark-600"
                  >
                    <span className="text-sm text-dark-300">
                      <span className="font-mono text-primary-400">
                        {getTableAlias(join.leftTableId)}
                      </span>
                      <span className="text-dark-500">.</span>
                      <span className="font-mono text-dark-200">{join.leftColumn}</span>
                      <span className="text-dark-500 mx-1">=</span>
                      <span className="font-mono text-primary-400">
                        {getTableAlias(join.rightTableId)}
                      </span>
                      <span className="text-dark-500">.</span>
                      <span className="font-mono text-dark-200">{join.rightColumn}</span>
                    </span>
                    <button
                      onClick={() => addJoin({ ...join, id: `join-${Date.now()}` })}
                      className="ml-auto flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 transition-colors"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      Add
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {joins.length === 0 && suggestedJoins.length === 0 ? (
            <p className="text-sm text-dark-500">No JOINs configured</p>
          ) : (
            joins.map((join) => (
              <div
                key={join.id}
                className="p-3 bg-dark-800 rounded-lg border border-dark-600"
              >
                <div className="flex items-center gap-2 mb-2">
                  <select
                    value={join.type}
                    onChange={(e) =>
                      updateJoinType(join.id, e.target.value as JoinType)
                    }
                    className={`px-2 py-1 text-xs font-semibold rounded border ${getJoinColor(
                      join.type
                    )} bg-transparent focus:outline-none`}
                  >
                    {JOIN_TYPES.map((type) => (
                      <option key={type} value={type} className="bg-dark-800">
                        {type}
                      </option>
                    ))}
                  </select>
                  <span className="text-xs text-dark-500">
                    {getJoinDescription(join.type)}
                  </span>
                  <button
                    onClick={() => removeJoin(join.id)}
                    className="ml-auto p-1 text-dark-500 hover:text-red-400 transition-colors"
                    title="Remove JOIN"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-mono text-primary-400">
                    {getTableAlias(join.leftTableId)}
                  </span>
                  <span className="text-dark-500">.</span>
                  <span className="font-mono text-dark-200">{join.leftColumn}</span>
                  <span className="text-dark-400 mx-1">=</span>
                  <span className="font-mono text-primary-400">
                    {getTableAlias(join.rightTableId)}
                  </span>
                  <span className="text-dark-500">.</span>
                  <span className="font-mono text-dark-200">{join.rightColumn}</span>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
