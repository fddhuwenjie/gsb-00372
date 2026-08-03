import { useState, useEffect, useCallback } from 'react';
import {
  FileText, Play, Plus, Trash2, ChevronDown, ChevronRight,
  Save, AlertTriangle, Check, Loader2, Share2,
} from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { QueryTemplate, TemplateParameter } from '@/types';
import {
  getTemplates, createTemplate, deleteTemplate,
  instantiateTemplate, executeTemplate,
} from '@/services/api';

export default function TemplatePanel() {
  const [templates, setTemplates] = useState<QueryTemplate[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [paramValues, setParamValues] = useState<Record<string, any>>({});
  const [executing, setExecuting] = useState(false);
  const [instantiated, setInstantiated] = useState<{ sql: string; params: Record<string, any> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [showSaveForm, setShowSaveForm] = useState(false);

  const queryStructure = useQueryStore((s) => s.getQueryStructure());
  const loadQueryStructure = useQueryStore((s) => s.loadQueryStructure);
  const setActiveTab = useQueryStore((s) => s.setActiveTab);
  const setQueryResult = useQueryStore((s) => s.setQueryResult);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getTemplates();
      setTemplates(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load templates');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const selectedTemplate = templates.find((t) => t.id === selectedId) || null;

  useEffect(() => {
    if (selectedTemplate) {
      const defaults: Record<string, any> = {};
      for (const p of selectedTemplate.parameters) {
        if (p.default !== undefined && p.default !== null) {
          defaults[p.name] = p.default;
        }
      }
      setParamValues(defaults);
      setInstantiated(null);
      setError(null);
    }
  }, [selectedId]);

  const handleSelect = (tpl: QueryTemplate) => {
    setSelectedId(tpl.id);
  };

  const handleInstantiate = async () => {
    if (!selectedTemplate) return;
    setError(null);
    try {
      const result = await instantiateTemplate(selectedTemplate.id, paramValues);
      setInstantiated({ sql: result.sql, params: result.params });
      loadQueryStructure(result.queryStructure);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to instantiate');
    }
  };

  const handleExecute = async () => {
    if (!selectedTemplate) return;
    setExecuting(true);
    setError(null);
    try {
      const result = await executeTemplate(selectedTemplate.id, paramValues);
      setQueryResult(result);
      setInstantiated({ sql: result.sql || '', params: result.params || {} });
      setActiveTab('result');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to execute');
    } finally {
      setExecuting(false);
    }
  };

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this template?')) return;
    try {
      await deleteTemplate(id);
      if (selectedId === id) {
        setSelectedId(null);
        setInstantiated(null);
      }
      loadTemplates();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete');
    }
  };

  const handleSaveAsTemplate = async () => {
    if (!newName.trim()) return;
    setSavingTemplate(true);
    setError(null);
    try {
      const created = await createTemplate({
        name: newName.trim(),
        description: newDescription.trim(),
        query_structure: queryStructure,
        parameters: [],
      });
      setTemplates((prev) => [created, ...prev]);
      setSelectedId(created.id);
      setNewName('');
      setNewDescription('');
      setShowSaveForm(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setSavingTemplate(false);
    }
  };

  const renderParamInput = (param: TemplateParameter) => {
    const value = paramValues[param.name];

    if (param.type === 'boolean') {
      return (
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => setParamValues((v) => ({ ...v, [param.name]: e.target.checked }))}
            className="w-4 h-4 rounded border-dark-500 bg-dark-700 text-primary-500"
          />
          <span className="text-sm text-dark-200">{value ? 'true' : 'false'}</span>
        </label>
      );
    }

    if (param.type === 'date') {
      return (
        <input
          type="date"
          value={value || ''}
          onChange={(e) => setParamValues((v) => ({ ...v, [param.name]: e.target.value }))}
          className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
        />
      );
    }

    if (param.type === 'date_range') {
      const dr = value || { start: '', end: '' };
      return (
        <div className="flex items-center gap-2 flex-1">
          <input
            type="date"
            value={dr.start || ''}
            onChange={(e) => setParamValues((v) => ({
              ...v,
              [param.name]: { ...dr, start: e.target.value },
            }))}
            className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
          />
          <span className="text-dark-500 text-xs">to</span>
          <input
            type="date"
            value={dr.end || ''}
            onChange={(e) => setParamValues((v) => ({
              ...v,
              [param.name]: { ...dr, end: e.target.value },
            }))}
            className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
          />
        </div>
      );
    }

    if (param.type === 'integer' || param.type === 'number') {
      return (
        <input
          type="number"
          step={param.type === 'number' ? 'any' : '1'}
          value={value ?? ''}
          onChange={(e) => {
            const raw = e.target.value;
            const parsed = param.type === 'integer' ? parseInt(raw, 10) : parseFloat(raw);
            setParamValues((v) => ({ ...v, [param.name]: isNaN(parsed) ? raw : parsed }));
          }}
          className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
        />
      );
    }

    if (param.type === 'string_list' || param.type === 'integer_list') {
      return (
        <input
          type="text"
          value={Array.isArray(value) ? value.join(', ') : ''}
          placeholder={param.type === 'integer_list' ? '1, 2, 3' : 'a, b, c'}
          onChange={(e) => {
            const parts = e.target.value.split(',').map((s) => s.trim()).filter(Boolean);
            const coerced = param.type === 'integer_list'
              ? parts.map((p) => parseInt(p, 10)).filter((n) => !isNaN(n))
              : parts;
            setParamValues((v) => ({ ...v, [param.name]: coerced }));
          }}
          className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
        />
      );
    }

    return (
      <input
        type="text"
        value={value ?? ''}
        onChange={(e) => setParamValues((v) => ({ ...v, [param.name]: e.target.value }))}
        className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
      />
    );
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 border-b border-dark-700 flex-shrink-0">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-medium text-dark-200">Query Templates</span>
        </div>
        <button
          onClick={() => setShowSaveForm(!showSaveForm)}
          className="flex items-center gap-1 px-2 py-1 text-xs bg-cyan-600 hover:bg-cyan-500 text-white rounded transition-colors"
        >
          <Save className="w-3 h-3" />
          Save Current
        </button>
      </div>

      {error && (
        <div className="mx-3 mt-2 p-2 bg-red-900/30 border border-red-800 rounded text-xs text-red-300 flex items-start gap-2 flex-shrink-0">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {showSaveForm && (
        <div className="mx-3 mt-2 p-3 bg-dark-800 rounded border border-dark-600 space-y-2 flex-shrink-0">
          <input
            type="text"
            placeholder="Template name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="w-full bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-100 focus:outline-none focus:border-primary-500"
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
            className="w-full bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500"
          />
          <div className="flex gap-2">
            <button
              onClick={handleSaveAsTemplate}
              disabled={savingTemplate || !newName.trim()}
              className="flex items-center gap-1 px-3 py-1 text-xs bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors disabled:opacity-50"
            >
              {savingTemplate ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
              Save
            </button>
            <button
              onClick={() => { setShowSaveForm(false); setNewName(''); setNewDescription(''); }}
              className="px-3 py-1 text-xs bg-dark-700 hover:bg-dark-600 text-dark-300 rounded transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        <div className="w-56 border-r border-dark-700 overflow-y-auto flex-shrink-0">
          {loading ? (
            <div className="p-4 text-center text-dark-400 text-sm">Loading...</div>
          ) : templates.length === 0 ? (
            <div className="p-4 text-center text-dark-500 text-xs">
              <FileText className="w-8 h-8 mx-auto mb-2 opacity-40" />
              No templates yet
            </div>
          ) : (
            templates.map((tpl) => (
              <div
                key={tpl.id}
                onClick={() => handleSelect(tpl)}
                className={`p-3 cursor-pointer border-b border-dark-700/50 transition-colors ${
                  selectedId === tpl.id ? 'bg-cyan-900/20 border-l-2 border-l-cyan-500' : 'hover:bg-dark-700/50'
                }`}
              >
                <div className="flex items-start justify-between gap-1">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-dark-100 truncate">{tpl.name}</div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-[10px] bg-dark-700 text-dark-400 px-1 rounded">v{tpl.version}</span>
                      <span className="text-[10px] text-dark-500">{tpl.parameters.length} params</span>
                    </div>
                  </div>
                  <button
                    onClick={(e) => handleDelete(tpl.id, e)}
                    className="p-1 text-dark-500 hover:text-red-400 transition-colors flex-shrink-0"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {!selectedTemplate ? (
            <div className="h-full flex flex-col items-center justify-center text-dark-500">
              <FileText className="w-12 h-12 mb-2 opacity-30" />
              <p className="text-sm">Select a template or save the current query</p>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <h3 className="text-base font-semibold text-dark-100">{selectedTemplate.name}</h3>
                {selectedTemplate.description && (
                  <p className="text-xs text-dark-400 mt-1">{selectedTemplate.description}</p>
                )}
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="text-[10px] bg-cyan-900/50 text-cyan-300 px-1.5 py-0.5 rounded">v{selectedTemplate.version}</span>
                  <span className="text-[10px] text-dark-500">
                    {selectedTemplate.schema_refs.length} field references
                  </span>
                </div>
              </div>

              {selectedTemplate.parameters.length > 0 ? (
                <div className="space-y-3">
                  <h4 className="text-xs font-semibold text-dark-300 uppercase tracking-wide">Parameters</h4>
                  {selectedTemplate.parameters.map((param) => (
                    <div key={param.name} className="space-y-1">
                      <div className="flex items-center gap-2">
                        <label className="text-sm text-dark-200 font-medium">
                          {param.label || param.name}
                          {param.required && <span className="text-red-400 ml-0.5">*</span>}
                        </label>
                        <span className="text-[10px] bg-dark-700 text-dark-400 px-1.5 py-0.5 rounded">
                          {param.type}
                        </span>
                      </div>
                      {param.description && (
                        <p className="text-xs text-dark-500">{param.description}</p>
                      )}
                      {renderParamInput(param)}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-3 bg-dark-800 rounded border border-dark-700 text-xs text-dark-400">
                  This template has no parameters. It will run the saved query as-is.
                </div>
              )}

              <div className="flex items-center gap-2 pt-2 border-t border-dark-700">
                <button
                  onClick={handleInstantiate}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-dark-700 hover:bg-dark-600 text-dark-200 rounded transition-colors"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                  Instantiate
                </button>
                <button
                  onClick={handleExecute}
                  disabled={executing}
                  className="flex items-center gap-1.5 px-4 py-1.5 text-xs bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors disabled:opacity-50"
                >
                  {executing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                  Execute
                </button>
              </div>

              {instantiated && (
                <div className="space-y-2">
                  <h4 className="text-xs font-semibold text-dark-300 uppercase tracking-wide">Generated SQL</h4>
                  <pre className="p-3 bg-dark-900 rounded-lg overflow-x-auto text-xs font-mono text-dark-200 max-h-48 overflow-y-auto whitespace-pre-wrap">
                    {instantiated.sql}
                  </pre>
                  {Object.keys(instantiated.params).length > 0 && (
                    <div className="p-2 bg-dark-800 rounded border border-dark-700">
                      <div className="text-[10px] text-dark-500 mb-1">Bound parameters:</div>
                      <code className="text-xs text-emerald-300 font-mono break-all">
                        {JSON.stringify(instantiated.params)}
                      </code>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
