import { useState } from 'react';
import { X, Save } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';

interface SaveDialogProps {
  onClose: () => void;
}

export default function SaveDialog({ onClose }: SaveDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentSavedId = useQueryStore((state) => state.currentSavedId);
  const saveQuery = useQueryStore((state) => state.saveQuery);
  const updateCurrentQuery = useQueryStore((state) => state.updateCurrentQuery);
  const savedQueries = useQueryStore((state) => state.savedQueries);

  const currentSaved = savedQueries.find((q) => q.id === currentSavedId);

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Name is required');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      if (currentSavedId) {
        await updateCurrentQuery();
      } else {
        await saveQuery(name.trim(), description.trim());
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save query');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-dark-800 rounded-lg border border-dark-600 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-dark-700">
          <h2 className="text-lg font-semibold text-dark-100">
            {currentSavedId ? 'Update Query' : 'Save Query'}
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-dark-400 hover:text-dark-200 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {error && (
            <div className="p-3 bg-red-900/30 border border-red-800 rounded text-sm text-red-300">
              {error}
            </div>
          )}

          {currentSaved && (
            <div className="p-3 bg-primary-900/20 border border-primary-800 rounded text-sm text-primary-300">
              Currently editing: <strong>{currentSaved.name}</strong>
            </div>
          )}

          {!currentSavedId && (
            <>
              <div>
                <label className="block text-sm font-medium text-dark-200 mb-1">
                  Name *
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Enter query name"
                  className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 placeholder-dark-500 focus:outline-none focus:border-primary-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-dark-200 mb-1">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Optional description"
                  rows={3}
                  className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 placeholder-dark-500 focus:outline-none focus:border-primary-500 resize-none"
                />
              </div>
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-dark-700">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-dark-300 hover:text-dark-100 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || (!currentSavedId && !name.trim())}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save className="w-4 h-4" />
            {saving ? 'Saving...' : currentSavedId ? 'Update' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
