import { useEffect, useState } from 'react';
import { LayoutTemplate, Play, Trash2, Plus, X, AlertTriangle, RefreshCw, GitCompare, Layers } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import { ApiError } from '@/services/api';
import { defaultRawValue, validateTemplateValue } from '@/lib/templateParams';
import CompareDialog from './CompareDialog';
import BatchRunDialog from './BatchRunDialog';
import type { QueryTemplate, TemplateIssue, TemplateParameter } from '@/types';

function ParamInput({
  param,
  raw,
  error,
  onChange,
}: {
  param: TemplateParameter;
  raw: string;
  error?: string;
  onChange: (raw: string) => void;
}) {
  const baseClass =
    'w-full bg-dark-700 border rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500';
  const borderClass = error ? 'border-red-600' : 'border-dark-600';

  return (
    <div>
      <label className="flex items-center gap-1 text-xs text-dark-400 mb-1">
        <span className="font-mono text-dark-300">{param.name}</span>
        <span className="text-dark-600">({param.type})</span>
        {param.required && <span className="text-red-400">*</span>}
      </label>
      {param.type === 'boolean' ? (
        <select
          value={raw}
          onChange={(e) => onChange(e.target.value)}
          className={`${baseClass} ${borderClass}`}
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : (
        <input
          type={param.type === 'date' ? 'date' : 'text'}
          value={raw}
          placeholder={param.type.endsWith('[]') ? 'value1, value2, ...' : param.type}
          onChange={(e) => onChange(e.target.value)}
          className={`${baseClass} ${borderClass}`}
        />
      )}
      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
    </div>
  );
}

function InstantiateDialog({
  template,
  onClose,
}: {
  template: QueryTemplate;
  onClose: () => void;
}) {
  const instantiateTemplate = useQueryStore((state) => state.instantiateTemplate);
  const [rawValues, setRawValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const param of template.parameters) {
      initial[param.name] = defaultRawValue(param);
    }
    return initial;
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [issues, setIssues] = useState<TemplateIssue[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    const values: Record<string, unknown> = {};
    const errors: Record<string, string> = {};
    for (const param of template.parameters) {
      const raw = rawValues[param.name] ?? '';
      const result = validateTemplateValue(param, raw);
      if (!result.ok) {
        errors[param.name] = result.error;
      } else {
        values[param.name] = result.value;
      }
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    setSubmitError(null);
    setIssues([]);
    try {
      await instantiateTemplate(template.id, values);
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(err.message);
        setIssues(err.issues ?? []);
      } else {
        setSubmitError(err instanceof Error ? err.message : 'Instantiation failed');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-dark-800 border border-dark-600 rounded-lg p-5 w-[420px] max-h-[80vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-dark-100 flex items-center gap-2">
            <LayoutTemplate className="w-4 h-4 text-primary-400" />
            {template.name}
            <span className="text-xs text-dark-500">v{template.version}</span>
          </h3>
          <button onClick={onClose} className="p-1 text-dark-400 hover:text-dark-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-xs text-dark-500 mb-4">
          Fill in parameter values - only values are substituted, the query structure is fixed.
        </p>

        <div className="space-y-3">
          {template.parameters.length === 0 && (
            <p className="text-sm text-dark-500">This template has no parameters.</p>
          )}
          {template.parameters.map((param) => (
            <ParamInput
              key={param.id}
              param={param}
              raw={rawValues[param.name] ?? ''}
              error={fieldErrors[param.name]}
              onChange={(raw) => setRawValues((prev) => ({ ...prev, [param.name]: raw }))}
            />
          ))}
        </div>

        {submitError && (
          <div className="mt-4 p-3 bg-red-900/20 border border-red-800 rounded text-sm text-red-300">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{submitError}</span>
            </div>
            {issues.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs">
                {issues.map((issue, i) => (
                  <li key={i} className="font-mono">
                    <span className="text-red-400">[{issue.code}]</span>{' '}
                    <span className="text-dark-400">{issue.path}:</span> {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-dark-300 hover:text-dark-100 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded transition-colors disabled:opacity-50"
          >
            {submitting ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            Run
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TemplatesPanel() {
  const templates = useQueryStore((state) => state.templates);
  const isLoading = useQueryStore((state) => state.isLoadingTemplates);
  const loadTemplates = useQueryStore((state) => state.loadTemplates);
  const saveAsTemplate = useQueryStore((state) => state.saveAsTemplate);
  const removeTemplate = useQueryStore((state) => state.removeTemplate);
  const tables = useQueryStore((state) => state.tables);
  const storeError = useQueryStore((state) => state.error);

  const [activeTemplate, setActiveTemplate] = useState<QueryTemplate | null>(null);
  const [compareTemplate, setCompareTemplate] = useState<QueryTemplate | null>(null);
  const [batchTemplate, setBatchTemplate] = useState<QueryTemplate | null>(null);
  const [newName, setNewName] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveIssues, setSaveIssues] = useState<TemplateIssue[]>([]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const handleSave = async () => {
    if (!newName.trim()) return;
    setSaveError(null);
    setSaveIssues([]);
    try {
      await saveAsTemplate(newName.trim());
      setNewName('');
    } catch (err) {
      if (err instanceof ApiError) {
        setSaveError(err.message);
        setSaveIssues(err.issues ?? []);
      } else {
        setSaveError(err instanceof Error ? err.message : 'Failed to save template');
      }
    }
  };

  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="flex items-center gap-2 mb-3">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder={tables.length === 0 ? 'Add tables to canvas first' : 'Template name...'}
          disabled={tables.length === 0}
          className="flex-1 bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200 focus:outline-none focus:border-primary-500 disabled:opacity-50"
        />
        <button
          onClick={handleSave}
          disabled={!newName.trim() || tables.length === 0}
          className="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded transition-colors disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />
          Save as template
        </button>
      </div>

      {(saveError || storeError) && (
        <div className="mb-3 p-3 bg-red-900/20 border border-red-800 rounded text-sm text-red-300">
          {saveError || storeError}
          {saveIssues.length > 0 && (
            <ul className="mt-1 space-y-1 text-xs font-mono">
              {saveIssues.map((issue, i) => (
                <li key={i}>
                  [{issue.code}] {issue.path}: {issue.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="p-8 text-center text-dark-400">Loading...</div>
      ) : templates.length === 0 ? (
        <div className="p-8 text-center text-dark-400">
          <LayoutTemplate className="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p>No templates yet</p>
          <p className="text-xs mt-1">
            Build a query, then save it as a reusable parameterized template
          </p>
        </div>
      ) : (
        <div className="divide-y divide-dark-700">
          {templates.map((template) => (
            <div key={template.id} className="p-3 hover:bg-dark-700/50 transition-colors">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <h3 className="font-medium text-dark-100 text-sm truncate flex items-center gap-2">
                    {template.name}
                    <span className="text-xs bg-dark-700 text-dark-400 px-1.5 py-0.5 rounded">
                      v{template.version}
                    </span>
                    <span className="text-xs text-dark-500">
                      {template.parameters.length} params
                    </span>
                  </h3>
                  {template.description && (
                    <p className="text-xs text-dark-400 mt-1 line-clamp-1">
                      {template.description}
                    </p>
                  )}
                  <p className="text-xs text-dark-500 mt-1">
                    Updated: {new Date(template.updated_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                  <button
                    onClick={() => removeTemplate(template.id)}
                    className="p-1.5 text-dark-400 hover:text-red-400 transition-colors rounded hover:bg-dark-600"
                    title="Delete template"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setCompareTemplate(template)}
                    className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-600"
                    title="Compare versions"
                  >
                    <GitCompare className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setBatchTemplate(template)}
                    className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-600"
                    title="Batch parameter run"
                  >
                    <Layers className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setActiveTemplate(template)}
                    className="px-2.5 py-1 text-xs bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors flex items-center gap-1"
                  >
                    <Play className="w-3 h-3" />
                    Run
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTemplate && (
        <InstantiateDialog template={activeTemplate} onClose={() => setActiveTemplate(null)} />
      )}
      {compareTemplate && (
        <CompareDialog template={compareTemplate} onClose={() => setCompareTemplate(null)} />
      )}
      {batchTemplate && (
        <BatchRunDialog template={batchTemplate} onClose={() => setBatchTemplate(null)} />
      )}
    </div>
  );
}
