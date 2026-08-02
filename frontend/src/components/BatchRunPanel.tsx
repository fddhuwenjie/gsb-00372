import { useEffect, useRef, useState } from 'react';
import { Layers, Play, X, RotateCcw, Plus, Trash2, RefreshCw } from 'lucide-react';
import type { QueryTemplate, BatchRun, BatchItemStatus } from '@/types';
import { submitBatchRun, getBatchRun, cancelBatchRun, retryBatchRun } from '@/services/api';
import ParamForm from './ParamForm';

interface BatchRunPanelProps {
  template: QueryTemplate;
}

const STATUS_STYLES: Record<BatchItemStatus, string> = {
  pending: 'text-dark-400 bg-dark-700/50',
  running: 'text-sky-300 bg-sky-900/30',
  succeeded: 'text-emerald-300 bg-emerald-900/30',
  failed: 'text-red-300 bg-red-900/30',
  rejected: 'text-orange-300 bg-orange-900/30',
  cancelled: 'text-dark-400 bg-dark-700/50',
};

export default function BatchRunPanel({ template }: BatchRunPanelProps) {
  const [valueSets, setValueSets] = useState<Record<string, any>[]>([{}, {}]);
  const [concurrency, setConcurrency] = useState(2);
  const [maxTotalRows, setMaxTotalRows] = useState<number | ''>('');
  const [maxTotalMs, setMaxTotalMs] = useState<number | ''>('');
  const [batch, setBatch] = useState<BatchRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<number | null>(null);

  // Keep the submitted value sets so a retry can resupply them (values are
  // never persisted server-side).
  const submittedSets = useRef<Record<string, any>[]>([]);

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const startPolling = (batchId: number) => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const b = await getBatchRun(batchId);
        setBatch(b);
        if (['completed', 'cancelled', 'failed'].includes(b.status)) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        /* keep polling */
      }
    }, 400);
  };

  const setParamValue = (index: number, name: string, value: any) => {
    setValueSets((sets) => sets.map((s, i) => (i === index ? { ...s, [name]: value } : s)));
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      submittedSets.current = valueSets;
      const b = await submitBatchRun(template.id, {
        value_sets: valueSets,
        version: template.current_version,
        max_concurrency: concurrency,
        max_total_rows: maxTotalRows === '' ? undefined : Number(maxTotalRows),
        max_total_ms: maxTotalMs === '' ? undefined : Number(maxTotalMs),
      });
      setBatch(b);
      startPolling(b.id);
    } catch (err: any) {
      setError(err?.message || 'Failed to submit');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async () => {
    if (!batch) return;
    const b = await cancelBatchRun(batch.id);
    setBatch(b);
  };

  const handleRetry = async () => {
    if (!batch) return;
    const b = await retryBatchRun(batch.id, submittedSets.current);
    setBatch(b);
    startPolling(batch.id);
  };

  const canRetry = batch && ['completed', 'cancelled', 'failed'].includes(batch.status) &&
    batch.items?.some((it) => it.status !== 'succeeded');

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm text-dark-200">
        <Layers className="w-4 h-4 text-primary-400" />
        <span className="font-medium">Batch run — v{template.current_version}</span>
      </div>

      {/* Budgets */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1 text-dark-300">
          Concurrency
          <input type="number" min={1} max={16} value={concurrency}
            onChange={(e) => setConcurrency(parseInt(e.target.value, 10) || 1)}
            className="w-16 bg-dark-700 border border-dark-600 rounded px-2 py-1 text-dark-200" />
        </label>
        <label className="flex items-center gap-1 text-dark-300">
          Max total rows
          <input type="number" min={1} value={maxTotalRows}
            onChange={(e) => setMaxTotalRows(e.target.value === '' ? '' : parseInt(e.target.value, 10))}
            className="w-24 bg-dark-700 border border-dark-600 rounded px-2 py-1 text-dark-200" placeholder="∞" />
        </label>
        <label className="flex items-center gap-1 text-dark-300">
          Max total ms
          <input type="number" min={1} value={maxTotalMs}
            onChange={(e) => setMaxTotalMs(e.target.value === '' ? '' : parseInt(e.target.value, 10))}
            className="w-24 bg-dark-700 border border-dark-600 rounded px-2 py-1 text-dark-200" placeholder="∞" />
        </label>
      </div>

      {/* Parameter sets */}
      <div className="space-y-2">
        {valueSets.map((vs, i) => (
          <div key={i} className="p-2 bg-dark-800 rounded border border-dark-700">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-dark-400">Set #{i + 1}</span>
              {valueSets.length > 1 && (
                <button onClick={() => setValueSets((s) => s.filter((_, j) => j !== i))}
                  className="p-1 text-dark-500 hover:text-red-400">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
            <ParamForm parameters={template.parameters} values={vs}
              onChange={(name, v) => setParamValue(i, name, v)} />
          </div>
        ))}
        <button onClick={() => setValueSets((s) => [...s, {}])}
          className="flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300">
          <Plus className="w-3.5 h-3.5" /> Add parameter set
        </button>
      </div>

      <div className="flex items-center gap-2">
        <button onClick={handleSubmit} disabled={submitting}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded disabled:opacity-50">
          {submitting ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Run batch
        </button>
        {batch && batch.status === 'running' && (
          <button onClick={handleCancel}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-red-700 hover:bg-red-600 text-white text-sm rounded">
            <X className="w-4 h-4" /> Cancel
          </button>
        )}
        {canRetry && (
          <button onClick={handleRetry}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-700 hover:bg-amber-600 text-white text-sm rounded">
            <RotateCcw className="w-4 h-4" /> Retry failed
          </button>
        )}
      </div>

      {error && (
        <div className="p-3 bg-red-900/20 border border-red-800 rounded text-sm text-red-300">{error}</div>
      )}

      {batch && (
        <div className="space-y-2">
          <div className="flex items-center gap-3 text-xs text-dark-300">
            <span className="uppercase font-semibold">{batch.status}</span>
            <span>rows: {batch.total_rows}{batch.max_total_rows ? ` / ${batch.max_total_rows}` : ''}</span>
            {Object.entries(batch.counts)
              .filter(([, n]) => n > 0)
              .map(([s, n]) => <span key={s}>{s}: {n}</span>)}
          </div>
          <div className="border border-dark-700 rounded overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-dark-800">
                <tr>
                  <th className="text-left px-3 py-1.5 text-dark-400">#</th>
                  <th className="text-left px-3 py-1.5 text-dark-400">Status</th>
                  <th className="text-left px-3 py-1.5 text-dark-400">Rows</th>
                  <th className="text-left px-3 py-1.5 text-dark-400">ms</th>
                  <th className="text-left px-3 py-1.5 text-dark-400">Plan</th>
                  <th className="text-left px-3 py-1.5 text-dark-400">Detail</th>
                </tr>
              </thead>
              <tbody>
                {(batch.items || []).map((it) => (
                  <tr key={it.item_index} className="border-t border-dark-700">
                    <td className="px-3 py-1.5 text-dark-300 font-mono">{it.item_index}</td>
                    <td className="px-3 py-1.5">
                      <span className={`px-1.5 py-0.5 rounded ${STATUS_STYLES[it.status]}`}>{it.status}</span>
                    </td>
                    <td className="px-3 py-1.5 text-dark-300 font-mono">{it.row_count ?? '—'}</td>
                    <td className="px-3 py-1.5 text-dark-300 font-mono">{it.duration_ms ?? '—'}</td>
                    <td className="px-3 py-1.5 text-dark-400 font-mono">{it.plan_record_id ?? '—'}</td>
                    <td className="px-3 py-1.5 text-dark-500 truncate max-w-[220px]" title={it.error || ''}>
                      {it.error || (it.param_type_summary ? Object.entries(it.param_type_summary.byName).map(([k, v]) => `${k}:${v}`).join(', ') : '')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
