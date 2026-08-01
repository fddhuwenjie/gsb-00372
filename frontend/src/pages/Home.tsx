import { useEffect, useState } from 'react';
import TableList from '@/components/TableList';
import QueryCanvas from '@/components/QueryCanvas';
import SQLPanel from '@/components/SQLPanel';
import WhereEditor from '@/components/WhereEditor';
import JoinEditor from '@/components/JoinEditor';
import CTEPane from '@/components/CTEPane';
import TabsPanel from '@/components/TabsPanel';
import Toolbar from '@/components/Toolbar';
import { useQueryStore } from '@/store/queryStore';
import { getMetadata } from '@/services/api';
import { Database, Loader2, AlertCircle } from 'lucide-react';

export default function Home() {
  const setMetadata = useQueryStore((state) => state.setMetadata);
  const error = useQueryStore((state) => state.error);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [, setDraggingTable] = useState<string | null>(null);

  useEffect(() => {
    const fetchMetadata = async () => {
      try {
        const data = await getMetadata();
        setMetadata(data);
        setLoading(false);
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : 'Failed to load metadata');
        setLoading(false);
      }
    };
    fetchMetadata();
  }, [setMetadata]);

  const handleDragStart = (tableName: string) => {
    setDraggingTable(tableName);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDraggingTable(null);
  };

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-dark-900">
        <div className="flex items-center gap-3 text-dark-300">
          <Loader2 className="w-6 h-6 animate-spin text-primary-400" />
          <span>Loading database metadata...</span>
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="h-screen flex items-center justify-center bg-dark-900">
        <div className="flex flex-col items-center gap-3 text-dark-300 max-w-md text-center">
          <AlertCircle className="w-10 h-10 text-red-400" />
          <h2 className="text-lg font-semibold text-dark-100">Failed to Load</h2>
          <p className="text-sm">{loadError}</p>
          <p className="text-xs text-dark-500 mt-2">
            Make sure the backend server is running on port 5000
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-dark-900">
      <header className="flex-shrink-0 bg-dark-800 border-b border-dark-700 px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Database className="w-7 h-7 text-primary-400" />
            <div>
              <h1 className="text-xl font-bold text-dark-100">Visual SQL Builder</h1>
              <p className="text-xs text-dark-400">Drag tables to build queries visually</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {error && (
              <div className="text-xs bg-red-900/30 text-red-300 px-3 py-1 rounded max-w-md truncate">
                {error}
              </div>
            )}
            <div className="text-right">
              <div className="text-xs text-dark-500">Database</div>
              <div className="text-sm font-medium text-primary-400">sakila.db</div>
            </div>
          </div>
        </div>
      </header>

      <Toolbar />

      <div className="flex-1 flex overflow-hidden">
        <aside className="w-72 flex-shrink-0 bg-dark-800 border-r border-dark-700 overflow-hidden flex flex-col">
          <TableList onDragStart={handleDragStart} />
        </aside>

        <main className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 min-h-0">
            <QueryCanvas onDrop={handleDrop} onDragOver={handleDragOver} />
          </div>
        </main>

        <aside className="w-96 flex-shrink-0 bg-dark-800 border-l border-dark-700 overflow-hidden flex flex-col">
          <div className="flex-1 overflow-y-auto flex flex-col min-h-0">
            <JoinEditor />
            <WhereEditor />
            <CTEPane />
            <SQLPanel />
            <TabsPanel />
          </div>
        </aside>
      </div>
    </div>
  );
}
