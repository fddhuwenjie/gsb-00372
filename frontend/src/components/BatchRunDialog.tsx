import { useEffect, useRef, useState } from 'react';
import { X, Play, Plus, Trash2, RefreshCw, Ban, RotateCcw, Layers } from 'lucide-react';
import {
  cancelBatchRun, createBatchRun, getBatchRun, getBatchRunItems, retryBatchRun,
} from '@/services/api';
import { buildBatchItems, canRetry, emptyRow, itemStatusLabel } from '@/lib/batchRun';
import type { BatchRun, BatchRunItem, QueryTemplate } from '@/types';

/**
 * Batch parameter run dialog: edit N parameter sets, run them against one
 * immutable template version with bounded concurrency / total rows / total
 * time, watch live progress, cancel cooperatively and retry only the items
 * that did not succeed.
 */
export default function BatchRunDialog({
  template,
  onClose,
}: {
  template: QueryTemplate;
  onClose: () => void;
}) {
  const [rows, setRows] = useState(() => [emptyRow(template.parameters, 'row-1')]);
  const [rowErrors, setRowErrors] = useState<Record<string, Record<string, string>>>({});
  const [concurrency, setConcurrency] = useState(2);
  const [maxRows, setMaxRows] = useState(10000);
  const [maxTime, setMaxTime] = useState(60000);
  const [batch, setBatch] = useState<BatchRun | null>(null);
  const [items, setItems] = useState<BatchRunItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const rowCounter = useRef(1);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };
  useEffect(() => stopPolling, []);

  const refresh = async (batchId: number) => {
    const [b, its] = await Promise.all([getBatchRun(batchId), getBatchRunItems(batchId)]);
    setBatch(b);
    setItems(its);
    if (b.status !== 'running') {
      stopPolling();
    }
  };

  const startPolling = (batchId: number) => {
    stopPolling();
    pollRef.current = setInterval(() => {
      refresh(batchId).catch(() => stopPolling());
    }, 500);
  };

  const handleStart = async () => {
    const { items: payload, rowErrors: errors } = buildBatchItems(template.parameters, rows);
    setRowErrors(errors);
    if (Object.keys(errors).length > 0 || payload.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createBatchRun({
        template_id: template.id,
        items: payload,
        max_concurrency: concurrency,
        max_total_rows: maxRows,
        max_total_time_ms: maxTime,
        idempotency_key: `ui-${template.id}-${Date.now()}`,
      });
      setBatch(created);
      startPolling(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start batch run');
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async () => {
    if (!batch) return;
    const updated = await cancelBatchRun(batch.id);
    setBatch(updated);
  };

  const handleRetry = async () => {
    if (!batch) return;
    const updated = await retryBatchRun(batch.id);
    setBatch(updated);
    startPolling(updated.id);
  };

  const running = batch?.status === 'running';

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-dark-800 border border-dark-600 rounded-lg p-5 w-[640px] max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-dark-100 flex items-center gap-2">
            <Layers className="w-4 h-4 text-primary-400" />
            Batch run: {template.name}
            <span className="text-xs text-dark-500">v{template.version}</span>
          </h3>
          <button onClick={onClose} className="p-1 text-dark-400 hover:text-dark-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-xs text-dark-500 mb-4">
          One immutable template version × N parameter sets. Only values change.
        </p>

        {/* parameter-set rows */}
        <div className="space-y-2 mb-4">
          {rows.map((row, rowIndex) => (
            <div key={row.key} className="p-2 bg-dark-900 rounded border border-dark-700">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-dark-500 font-mono w-6">#{rowIndex}</span>
                {template.parameters.map((param) => (
                  <div key={param.id} className="flex-1 min-w-[110px]">
                    <label className="text-xs text-dark-500 font-mono">{param.name}</label>
                    <input
                      type="text"
                      value={row.raw[param.name] ?? ''}
                      disabled={running}
                      onChange={(e) =>
                        setRows((prev) =>
                          prev.map((r) =>
                            r.key === row.key
                              ? { ...r, raw: { ...r.raw, [param.name]: e.target.value } }
                              : r
                          )
                        )
                      }
                      className={`w-full bg-dark-700 border rounded px-1.5 py-1 text-xs text-dark-200 ${
                        rowErrors[row.key]?.[param.name] ? 'border-red-600' : 'border-dark-600'
                      }`}
                    />
                    {rowErrors[row.key]?.[param.name] && (
                      <p className="text-xs text-red-400">{rowErrors[row.key][param.name]}</p>
                    )}
                  </div>
                ))}
                <button
                  onClick={() => setRows((prev) => prev.filter((r) => r.key !== row.key))}
                  disabled={running || rows.length <= 1}
                  className="p-1 text-dark-500 hover:text-red-400 disabled:opacity-30"
                  title="Remove parameter set"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
          <button
            onClick={() => {
              rowCounter.current += 1;
              setRows((prev) => [...prev, emptyRow(template.parameters, `row-${rowCounter.current}`)]);
            }}
            disabled={running}
            className="flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 disabled:opacity-50"
          >
            <Plus className="w-3.5 h-3.5" />
            Add parameter set
          </button>
        </div>

        {/* limits */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          <label className="text-xs text-dark-500">
            Concurrency
            <input
              type="number" min={1} max={8} value={concurrency} disabled={running}
              onChange={(e) => setConcurrency(Number(e.target.value))}
              className="mt-1 w-full bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200"
            />
          </label>
          <label className="text-xs text-dark-500">
            Max total rows
            <input
              type="number" min={1} value={maxRows} disabled={running}
              onChange={(e) => setMaxRows(Number(e.target.value))}
              className="mt-1 w-full bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200"
            />
          </label>
          <label className="text-xs text-dark-500">
            Max total time (ms)
            <input
              type="number" min={100} value={maxTime} disabled={running}
              onChange={(e) => setMaxTime(Number(e.target.value))}
              className="mt-1 w-full bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200"
            />
          </label>
        </div>

        {error && (
          <div className="mb-3 p-3 bg-red-900/20 border border-red-800 rounded text-sm text-red-300">
            {error}
          </div>
        )}

        {/* actions */}
        <div className="flex items-center gap-2 mb-4">
          {!running && (
            <button
              onClick={handleStart}
              disabled={busy}
              className="flex items-center gap-1.5 px-4 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded transition-colors disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5" />
              Start batch
            </button>
          )}
          {running && (
            <button
              onClick={handleCancel}
              className="flex items-center gap-1.5 px-4 py-1.5 bg-red-600 hover:bg-red-500 text-white text-sm rounded transition-colors"
            >
              <Ban className="w-3.5 h-3.5" />
              Cancel
            </button>
          )}
          {batch && !running && canRetry(batch.status) && (
            <button
              onClick={handleRetry}
              className="flex items-center gap-1.5 px-4 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-sm rounded transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Retry unsuccessful
            </button>
          )}
        </div>

        {/* progress */}
        {batch && (
          <div className="space-y-2">
            <div className="flex items-center gap-3 text-xs font-mono text-dark-300 bg-dark-900 rounded px-2 py-1.5">
              <span className={
                batch.status === 'completed' ? 'text-emerald-400' :
                batch.status === 'cancelled' ? 'text-amber-400' :
                batch.status === 'failed' ? 'text-red-400' : 'text-primary-400'
              }>
                {batch.status}
                {batch.stopped_reason ? ` (${batch.stopped_reason})` : ''}
              </span>
              {running && <RefreshCw className="w-3 h-3 animate-spin text-primary-400" />}
              <span>
                ok {batch.succeeded_items} · fail {batch.failed_items} · cancel {batch.cancelled_items} · skip {batch.skipped_items} / {batch.total_items}
              </span>
              <span className="ml-auto">rows {batch.total_rows}</span>
            </div>
            <ul className="space-y-1">
              {items.map((item) => (
                <li key={item.id}
                    className="flex items-center gap-2 text-xs font-mono bg-dark-900 rounded px-2 py-1">
                  <span className="text-dark-500 w-8">#{item.seq}</span>
                  <span className={
                    item.status === 'succeeded' ? 'text-emerald-400' :
                    item.status === 'failed' ? 'text-red-400' :
                    item.status === 'cancelled' ? 'text-amber-400' :
                    item.status === 'skipped' ? 'text-dark-500' : 'text-primary-400'
                  }>
                    {itemStatusLabel(item.status)}
                  </span>
                  {item.status === 'succeeded' && (
                    <span className="text-dark-400">
                      {item.row_count} rows · {item.duration_ms}ms · hash {item.ast_hash}
                    </span>
                  )}
                  {item.status === 'failed' && (
                    <span className="text-red-400 truncate" title={item.error ?? ''}>
                      [{item.error_code}] {item.error}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
