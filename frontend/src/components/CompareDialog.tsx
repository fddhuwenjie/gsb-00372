import { useEffect, useState } from 'react';
import { GitCompare, X, RefreshCw, ArrowRight } from 'lucide-react';
import { compareTemplateVersions, getTemplateVersions, ApiError } from '@/services/api';
import { formatAstChange, formatPlanChange, groupAstChanges } from '@/lib/planChanges';
import { defaultRawValue, validateTemplateValue } from '@/lib/templateParams';
import type { CompareResult, QueryTemplate, TemplateVersionInfo } from '@/types';

/**
 * Compare two versions of one template. The change set is rendered by AST
 * node (JOIN edge, filter clause, aggregation, index access path), never
 * by SQL line numbers.
 */
export default function CompareDialog({
  template,
  onClose,
}: {
  template: QueryTemplate;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<TemplateVersionInfo[]>([]);
  const [fromVersion, setFromVersion] = useState<number | null>(null);
  const [toVersion, setToVersion] = useState<number>(template.version);
  const [rawValues, setRawValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const param of template.parameters) {
      initial[param.name] = defaultRawValue(param);
    }
    return initial;
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    getTemplateVersions(template.id)
      .then((list) => {
        setVersions(list);
        if (list.length >= 2) {
          setFromVersion(list[list.length - 2].version);
          setToVersion(list[list.length - 1].version);
        } else if (list.length === 1) {
          setFromVersion(list[0].version);
          setToVersion(list[0].version);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load versions'));
  }, [template.id]);

  const handleCompare = async () => {
    if (fromVersion === null) return;
    const values: Record<string, unknown> = {};
    const errors: Record<string, string> = {};
    for (const param of template.parameters) {
      const validation = validateTemplateValue(param, rawValues[param.name] ?? '');
      if (!validation.ok) {
        errors[param.name] = validation.error ?? 'invalid value';
      } else {
        values[param.name] = validation.value;
      }
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setRunning(true);
    setError(null);
    try {
      const compare = await compareTemplateVersions(template.id, {
        from_version: fromVersion,
        to_version: toVersion,
        values,
        include_results: true,
      });
      setResult(compare);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Compare failed');
    } finally {
      setRunning(false);
    }
  };

  const identical = result && result.ast_hash_from === result.ast_hash_to;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-dark-800 border border-dark-600 rounded-lg p-5 w-[560px] max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-dark-100 flex items-center gap-2">
            <GitCompare className="w-4 h-4 text-primary-400" />
            Compare {template.name} versions
          </h3>
          <button onClick={onClose} className="p-1 text-dark-400 hover:text-dark-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex items-center gap-2 mb-4">
          <select
            value={fromVersion ?? ''}
            onChange={(e) => setFromVersion(Number(e.target.value))}
            className="bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200"
          >
            {versions.map((v) => (
              <option key={v.version} value={v.version}>v{v.version}</option>
            ))}
          </select>
          <ArrowRight className="w-4 h-4 text-dark-500" />
          <select
            value={toVersion}
            onChange={(e) => setToVersion(Number(e.target.value))}
            className="bg-dark-700 border border-dark-600 rounded px-2 py-1.5 text-sm text-dark-200"
          >
            {versions.map((v) => (
              <option key={v.version} value={v.version}>v{v.version}</option>
            ))}
          </select>
          <button
            onClick={handleCompare}
            disabled={running || fromVersion === null || versions.length === 0}
            className="ml-auto flex items-center gap-1.5 px-4 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded transition-colors disabled:opacity-50"
          >
            {running ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
            Compare
          </button>
        </div>

        {template.parameters.length > 0 && (
          <div className="mb-4 p-3 bg-dark-900 rounded border border-dark-700">
            <div className="text-xs text-dark-400 mb-2">Parameter values (both versions)</div>
            <div className="grid grid-cols-2 gap-2">
              {template.parameters.map((param) => (
                <div key={param.id}>
                  <label className="text-xs text-dark-500 font-mono">{param.name}</label>
                  <input
                    type="text"
                    value={rawValues[param.name] ?? ''}
                    onChange={(e) =>
                      setRawValues((prev) => ({ ...prev, [param.name]: e.target.value }))
                    }
                    className={`w-full bg-dark-700 border rounded px-2 py-1 text-sm text-dark-200 ${
                      fieldErrors[param.name] ? 'border-red-600' : 'border-dark-600'
                    }`}
                  />
                  {fieldErrors[param.name] && (
                    <p className="text-xs text-red-400">{fieldErrors[param.name]}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="mb-3 p-3 bg-red-900/20 border border-red-800 rounded text-sm text-red-300">
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-4">
            <div className={`p-2 rounded text-xs font-mono ${
              identical ? 'bg-emerald-900/30 text-emerald-300' : 'bg-amber-900/30 text-amber-300'
            }`}>
              {identical
                ? `Identical plans (hash ${result.ast_hash_from})`
                : `Plans differ: ${result.ast_hash_from} → ${result.ast_hash_to}`}
            </div>

            {groupAstChanges(result.ast_changes).map((group) => (
              <div key={group.category}>
                <div className="text-xs font-semibold text-dark-300 mb-1">{group.label}</div>
                <ul className="space-y-1">
                  {group.changes.map((change, i) => (
                    <li key={i} className="text-xs font-mono text-dark-200 bg-dark-900 rounded px-2 py-1">
                      <span className={
                        change.change === 'added' ? 'text-emerald-400' :
                        change.change === 'removed' ? 'text-red-400' : 'text-amber-400'
                      }>
                        {change.change}
                      </span>{' '}
                      {formatAstChange(change)}
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            {result.plan_changes.length > 0 && (
              <div>
                <div className="text-xs font-semibold text-dark-300 mb-1">Index access</div>
                <ul className="space-y-1">
                  {result.plan_changes.map((change, i) => (
                    <li key={i} className="text-xs font-mono text-dark-200 bg-dark-900 rounded px-2 py-1">
                      {formatPlanChange(change)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {result.ast_changes.length === 0 && result.plan_changes.length === 0 && (
              <p className="text-xs text-dark-500">No semantic or plan changes between these versions.</p>
            )}

            {result.result_diff && (
              <div>
                <div className="text-xs font-semibold text-dark-300 mb-1">Result diff</div>
                <div className="text-xs font-mono text-dark-200 bg-dark-900 rounded px-2 py-1 space-y-0.5">
                  <div>rows: v{result.from_version}={result.result_diff.rows_from} → v{result.to_version}={result.result_diff.rows_to}</div>
                  <div>only in v{result.from_version}: {result.result_diff.rows_only_in_from} · only in v{result.to_version}: {result.result_diff.rows_only_in_to}</div>
                  {result.result_diff.columns_added.length > 0 && (
                    <div>columns added: {result.result_diff.columns_added.join(', ')}</div>
                  )}
                  {result.result_diff.columns_removed.length > 0 && (
                    <div>columns removed: {result.result_diff.columns_removed.join(', ')}</div>
                  )}
                  <div>duration: {result.result_diff.duration_from_ms}ms → {result.result_diff.duration_to_ms}ms</div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
