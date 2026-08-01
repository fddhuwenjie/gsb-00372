import { useState } from 'react';
import { Database, ChevronDown, ChevronRight, Key, Hash } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { TableMetadata } from '@/types';

interface TableListProps {
  onDragStart: (tableName: string) => void;
}

function TableItem({ table, onDragStart }: { table: TableMetadata; onDragStart: (tableName: string) => void }) {
  const [expanded, setExpanded] = useState(true);
  const tables = useQueryStore((state) => state.tables);
  const isAdded = tables.some((t) => t.tableName === table.name);

  const handleDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData('tableName', table.name);
    e.dataTransfer.effectAllowed = 'copy';
    onDragStart(table.name);
  };

  return (
    <div className="mb-2">
      <div
        draggable
        onDragStart={handleDragStart}
        className={`flex items-center gap-2 px-3 py-2 rounded cursor-move transition-all hover:bg-dark-700 ${
          isAdded ? 'opacity-50' : ''
        }`}
      >
        <button
          onClick={() => setExpanded(!expanded)}
          className="p-0.5 hover:bg-dark-600 rounded"
        >
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-dark-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-dark-400" />
          )}
        </button>
        <Database className="w-4 h-4 text-primary-400" />
        <span className="font-medium text-dark-100">{table.name}</span>
        {isAdded && (
          <span className="ml-auto text-xs text-primary-400 bg-primary-900/30 px-2 py-0.5 rounded">
            Added
          </span>
        )}
      </div>
      {expanded && (
        <div className="ml-8 mt-1 space-y-1">
          {table.columns.map((col) => (
            <div
              key={col.name}
              className="flex items-center gap-2 px-3 py-1.5 text-sm text-dark-300 hover:bg-dark-700/50 rounded"
            >
              {col.isPrimaryKey ? (
                <Key className="w-3.5 h-3.5 text-yellow-500" />
              ) : (
                <Hash className="w-3.5 h-3.5 text-dark-500" />
              )}
              <span>{col.name}</span>
              <span className="ml-auto text-xs text-dark-500">{col.type}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function TableList({ onDragStart }: TableListProps) {
  const metadata = useQueryStore((state) => state.metadata);

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b border-dark-700">
        <h2 className="text-lg font-semibold text-dark-100 flex items-center gap-2">
          <Database className="w-5 h-5 text-primary-400" />
          Tables
        </h2>
        <p className="text-xs text-dark-400 mt-1">Drag tables to canvas</p>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {metadata.map((table) => (
          <TableItem key={table.name} table={table} onDragStart={onDragStart} />
        ))}
      </div>
    </div>
  );
}
