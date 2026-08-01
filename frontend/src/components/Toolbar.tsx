import { useState } from 'react';
import { Save, FolderOpen, Share2, Play, Loader2 } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import SaveDialog from './SaveDialog';
import SharePanel from './SharePanel';
import OpenDialog from './OpenDialog';

export default function Toolbar() {
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showOpenDialog, setShowOpenDialog] = useState(false);
  const [showSharePanel, setShowSharePanel] = useState(false);
  const isExecuting = useQueryStore((state) => state.isExecuting);
  const executeQuery = useQueryStore((state) => state.executeQuery);
  const runExplain = useQueryStore((state) => state.runExplain);
  const isExplaining = useQueryStore((state) => state.isExplaining);
  const tables = useQueryStore((state) => state.tables);

  return (
    <>
      <div className="flex items-center gap-2 px-4 py-2 bg-dark-800 border-b border-dark-700">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowSaveDialog(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-dark-700 hover:bg-dark-600 text-dark-200 rounded transition-colors"
            title="Save Query"
          >
            <Save className="w-4 h-4" />
            <span>Save</span>
          </button>
          <button
            onClick={() => {
              setShowOpenDialog(true);
              useQueryStore.getState().loadSavedQueries();
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-dark-700 hover:bg-dark-600 text-dark-200 rounded transition-colors"
            title="Open Saved Query"
          >
            <FolderOpen className="w-4 h-4" />
            <span>Open</span>
          </button>
          <button
            onClick={() => setShowSharePanel(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-dark-700 hover:bg-dark-600 text-dark-200 rounded transition-colors"
            title="Share Query"
          >
            <Share2 className="w-4 h-4" />
            <span>Share</span>
          </button>
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-1">
          <button
            onClick={() => runExplain()}
            disabled={tables.length === 0 || isExplaining}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-purple-600 hover:bg-purple-500 text-white rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Explain Query Plan"
          >
            {isExplaining ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <span>Explain</span>
            )}
          </button>
          <button
            onClick={() => executeQuery()}
            disabled={tables.length === 0 || isExecuting}
            className="flex items-center gap-1.5 px-4 py-1.5 text-sm bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isExecuting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            <span>Execute</span>
          </button>
        </div>
      </div>

      {showSaveDialog && (
        <SaveDialog onClose={() => setShowSaveDialog(false)} />
      )}
      {showOpenDialog && (
        <OpenDialog onClose={() => setShowOpenDialog(false)} />
      )}
      {showSharePanel && (
        <SharePanel onClose={() => setShowSharePanel(false)} />
      )}
    </>
  );
}
