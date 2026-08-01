import { X, FolderOpen, Trash2, Download, Play } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import { exportQuery } from '@/services/api';

interface OpenDialogProps {
  onClose: () => void;
}

export default function OpenDialog({ onClose }: OpenDialogProps) {
  const savedQueries = useQueryStore((state) => state.savedQueries);
  const isLoadingSaved = useQueryStore((state) => state.isLoadingSaved);
  const loadQuery = useQueryStore((state) => state.loadQuery);
  const deleteQuery = useQueryStore((state) => state.deleteQuery);

  const handleLoad = (query: any) => {
    loadQuery(query);
    onClose();
  };

  const handleExecute = async (query: any) => {
    loadQuery(query);
    onClose();
    setTimeout(() => {
      useQueryStore.getState().executeQuery();
    }, 100);
  };

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    if (confirm('Are you sure you want to delete this query?')) {
      await deleteQuery(id);
    }
  };

  const handleExport = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    await exportQuery(id);
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-dark-800 rounded-lg border border-dark-600 w-full max-w-2xl shadow-2xl max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-dark-700 flex-shrink-0">
          <h2 className="text-lg font-semibold text-dark-100 flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-primary-400" />
            Saved Queries
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-dark-400 hover:text-dark-200 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoadingSaved ? (
            <div className="p-8 text-center text-dark-400">Loading...</div>
          ) : savedQueries.length === 0 ? (
            <div className="p-8 text-center text-dark-400">
              No saved queries yet
            </div>
          ) : (
            <div className="divide-y divide-dark-700">
              {savedQueries.map((query) => (
                <div
                  key={query.id}
                  className="p-4 hover:bg-dark-700/50 transition-colors"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-dark-100 truncate">
                        {query.name}
                      </h3>
                      {query.description && (
                        <p className="text-sm text-dark-400 mt-1 line-clamp-2">
                          {query.description}
                        </p>
                      )}
                      <p className="text-xs text-dark-500 mt-2">
                        Updated: {formatDate(query.updated_at)}
                        {query.share_token && (
                          <span className="ml-3 text-primary-400">
                            Shared ({query.share_access_count} views)
                          </span>
                        )}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 ml-4 flex-shrink-0">
                      <button
                        onClick={(e) => handleExport(e, query.id)}
                        className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-600"
                        title="Export SQL"
                      >
                        <Download className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleExecute(query)}
                        className="p-1.5 text-dark-400 hover:text-emerald-400 transition-colors rounded hover:bg-dark-600"
                        title="Load & Execute"
                      >
                        <Play className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleLoad(query)}
                        className="px-3 py-1 text-sm bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors"
                      >
                        Load
                      </button>
                      <button
                        onClick={(e) => handleDelete(e, query.id)}
                        className="p-1.5 text-dark-400 hover:text-red-400 transition-colors rounded hover:bg-dark-600"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
