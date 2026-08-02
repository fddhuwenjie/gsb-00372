import { useEffect, useState } from 'react';
import { FileCode, Play, Trash2, Share2, RefreshCw, AlertTriangle, GitCompare, Layers } from 'lucide-react';
import { useTemplateStore } from '@/store/templateStore';
import ParamForm from './ParamForm';
import PlanComparePanel from './PlanComparePanel';
import BatchRunPanel from './BatchRunPanel';

export default function TemplatesPanel() {
  const templates = useTemplateStore((s) => s.templates);
  const isLoading = useTemplateStore((s) => s.isLoading);
  const activeTemplate = useTemplateStore((s) => s.activeTemplate);
  const paramValues = useTemplateStore((s) => s.paramValues);
  const selectedVersion = useTemplateStore((s) => s.selectedVersion);
  const instanceResult = useTemplateStore((s) => s.instanceResult);
  const isRunning = useTemplateStore((s) => s.isRunning);
  const error = useTemplateStore((s) => s.error);
  const migration = useTemplateStore((s) => s.migration);

  const [showCompare, setShowCompare] = useState(false);
  const [showBatch, setShowBatch] = useState(false);

  const loadTemplates = useTemplateStore((s) => s.loadTemplates);
  const selectTemplate = useTemplateStore((s) => s.selectTemplate);
  const setSelectedVersion = useTemplateStore((s) => s.setSelectedVersion);
  const setParamValue = useTemplateStore((s) => s.setParamValue);
  const runActiveTemplate = useTemplateStore((s) => s.runActiveTemplate);
  const removeTemplate = useTemplateStore((s) => s.removeTemplate);
  const shareActiveTemplate = useTemplateStore((s) => s.shareActiveTemplate);
  const checkActiveSchema = useTemplateStore((s) => s.checkActiveSchema);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const handleShare = async () => {
    const res = await shareActiveTemplate();
    if (res) {
      await navigator.clipboard.writeText(`${window.location.origin}${res.url}`);
    }
  };

  return (
    <div className="h-full flex">
      {/* Template list */}
      <div className="w-1/3 border-r border-dark-700 overflow-y-auto">
        <div className="p-3 flex items-center justify-between border-b border-dark-700">
          <span className="text-sm font-medium text-dark-200">Templates</span>
          <button
            onClick={() => loadTemplates()}
            className="p-1 text-dark-400 hover:text-primary-400"
            title="Refresh"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
        {isLoading ? (
          <div className="p-4 text-center text-dark-400 text-sm">Loading...</div>
        ) : templates.length === 0 ? (
          <div className="p-6 text-center text-dark-400 text-sm">
            <FileCode className="w-10 h-10 mx-auto mb-2 opacity-50" />
            <p>No templates yet</p>
            <p className="text-xs mt-1">Use "Save as Template" from the toolbar</p>
          </div>
        ) : (
          <div className="divide-y divide-dark-700">
            {templates.map((t) => (
              <button
                key={t.id}
                onClick={() => selectTemplate(t)}
                className={`w-full text-left p-3 hover:bg-dark-700/50 transition-colors ${
                  activeTemplate?.id === t.id ? 'bg-primary-900/20' : ''
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-dark-100 truncate">{t.name}</span>
                  <span className="text-xs text-dark-500">v{t.current_version}</span>
                </div>
                {t.description && (
                  <p className="text-xs text-dark-400 mt-1 line-clamp-1">{t.description}</p>
                )}
                <p className="text-xs text-dark-500 mt-1">{t.parameters.length} params</p>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Active template panel */}
      <div className="flex-1 overflow-y-auto p-4">
        {!activeTemplate ? (
          <div className="h-full flex items-center justify-center text-dark-400 text-sm">
            Select a template to enter parameters
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-dark-100 font-medium">{activeTemplate.name}</h3>
                <p className="text-xs text-dark-400">{activeTemplate.description}</p>
              </div>
              <div className="flex items-center gap-2">
                {activeTemplate.versions && activeTemplate.versions.length > 1 && (
                  <select
                    value={selectedVersion ?? activeTemplate.current_version}
                    onChange={(e) => setSelectedVersion(parseInt(e.target.value, 10))}
                    className="bg-dark-700 border border-dark-600 rounded px-2 py-1 text-xs text-dark-200"
                  >
                    {activeTemplate.versions.map((v) => (
                      <option key={v.version} value={v.version}>
                        v{v.version}
                      </option>
                    ))}
                  </select>
                )}
                <button
                  onClick={() => checkActiveSchema()}
                  className="px-2 py-1 text-xs bg-dark-700 hover:bg-dark-600 text-dark-300 rounded"
                  title="Check against current schema"
                >
                  Check schema
                </button>
                {activeTemplate.versions && activeTemplate.versions.length > 1 && (
                  <button
                    onClick={() => setShowCompare((v) => !v)}
                    className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${
                      showCompare ? 'bg-primary-600 text-white' : 'bg-dark-700 hover:bg-dark-600 text-dark-300'
                    }`}
                    title="Compare execution plans across versions"
                  >
                    <GitCompare className="w-3.5 h-3.5" />
                    Compare
                  </button>
                )}
                <button
                  onClick={() => setShowBatch((v) => !v)}
                  className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${
                    showBatch ? 'bg-primary-600 text-white' : 'bg-dark-700 hover:bg-dark-600 text-dark-300'
                  }`}
                  title="Run many parameter sets as a cancellable batch"
                >
                  <Layers className="w-3.5 h-3.5" />
                  Batch
                </button>
                <button
                  onClick={handleShare}
                  className="p-1.5 text-dark-400 hover:text-primary-400 rounded hover:bg-dark-600"
                  title="Share template (copies link)"
                >
                  <Share2 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => removeTemplate(activeTemplate.id)}
                  className="p-1.5 text-dark-400 hover:text-red-400 rounded hover:bg-dark-600"
                  title="Delete template"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            {showCompare && activeTemplate.versions && activeTemplate.versions.length > 1 && (
              <div className="p-3 bg-dark-900 rounded border border-dark-700">
                <PlanComparePanel template={activeTemplate} />
              </div>
            )}

            {showBatch && (
              <div className="p-3 bg-dark-900 rounded border border-dark-700">
                <BatchRunPanel template={activeTemplate} />
              </div>
            )}

            <div className="p-3 bg-dark-800 rounded border border-dark-700">
              <ParamForm
                parameters={activeTemplate.parameters}
                values={paramValues}
                onChange={setParamValue}
              />
            </div>

            <button
              onClick={() => runActiveTemplate()}
              disabled={isRunning}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded disabled:opacity-50"
            >
              {isRunning ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              Run
            </button>

            {migration && migration.length > 0 && (
              <div className="p-3 bg-amber-900/20 border border-amber-800 rounded text-sm">
                <div className="flex items-center gap-2 text-amber-300 font-medium mb-2">
                  <AlertTriangle className="w-4 h-4" />
                  Schema migration required
                </div>
                <ul className="space-y-1 text-xs text-amber-200/90">
                  {migration.map((m, i) => (
                    <li key={i} className="font-mono">
                      {m.reason}: {m.tableName ?? '?'}.{m.columnName ?? '?'}{' '}
                      <span className="text-amber-400/70">(instance {m.tableInstanceId ?? '?'})</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {error && (!migration || migration.length === 0) && (
              <div className="p-3 bg-red-900/20 border border-red-800 rounded text-sm text-red-300">
                {error}
              </div>
            )}

            {instanceResult && (
              <div className="border border-dark-700 rounded overflow-hidden">
                <div className="px-3 py-2 bg-dark-800 text-xs text-dark-400 flex gap-3">
                  <span>{instanceResult.rowCount} rows</span>
                  <span>{instanceResult.executionTime}ms</span>
                </div>
                <div className="overflow-auto max-h-[280px]">
                  <table className="w-full text-xs">
                    <thead className="bg-dark-800 sticky top-0">
                      <tr>
                        {instanceResult.columns.map((col) => (
                          <th key={col.name} className="text-left px-3 py-1.5 text-dark-300 font-medium">
                            {col.name}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {instanceResult.rows.map((row, ri) => (
                        <tr key={ri} className="border-t border-dark-700">
                          {row.map((cell, ci) => (
                            <td key={ci} className="px-3 py-1.5 text-dark-200 font-mono">
                              {cell === null ? <span className="text-dark-500 italic">NULL</span> : String(cell)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
