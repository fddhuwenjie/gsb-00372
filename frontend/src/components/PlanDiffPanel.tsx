import { useState, useEffect, useCallback } from 'react';
import {
  GitCompare, Plus, Minus, RefreshCw, Clock,
  Database, KeyRound, Link2, Filter, Sigma, ArrowRight,
} from 'lucide-react';
import type {
  PlanSnapshot, PlanDiff, PlanOperation, AstChange, QueryStructure,
} from '@/types';
import {
  getPlanSnapshots, comparePlanSnapshots, createPlanSnapshot,
  comparePlanStructures,
} from '@/services/api';
import { useQueryStore } from '@/store/queryStore';

function astNodeLabel(key: string): { label: string; icon: React.ReactNode; color: string } {
  if (key.startsWith('table:')) {
    return { label: `Table ${key.slice(6)}`, icon: <Database className="w-3 h-3" />, color: 'text-blue-400' };
  }
  if (key.startsWith('join:')) {
    return { label: `JOIN ${key.slice(5)}`, icon: <Link2 className="w-3 h-3" />, color: 'text-purple-400' };
  }
  if (key.startsWith('filter:')) {
    return { label: `Filter ${key.slice(7)}`, icon: <Filter className="w-3 h-3" />, color: 'text-amber-400' };
  }
  if (key.startsWith('agg:')) {
    return { label: `Aggregation ${key.slice(4)}`, icon: <Sigma className="w-3 h-3" />, color: 'text-emerald-400' };
  }
  if (key === 'group_by') {
    return { label: 'GROUP BY', icon: <Sigma className="w-3 h-3" />, color: 'text-emerald-400' };
  }
  if (key === 'order_by') {
    return { label: 'ORDER BY', icon: <Clock className="w-3 h-3" />, color: 'text-cyan-400' };
  }
  return { label: key, icon: <Database className="w-3 h-3" />, color: 'text-dark-400' };
}

function changeTypeLabel(ct: string): string {
  const map: Record<string, string> = {
    table_index_added: 'Index added (table)',
    table_access_changed: 'Access path changed',
    join_index_added: 'Index added for JOIN',
    join_index_removed: 'Index removed for JOIN',
    join_access_changed: 'JOIN access changed',
    filter_uses_index: 'Filter now uses index',
    filter_index_dropped: 'Filter lost index',
    filter_access_changed: 'Filter access changed',
    aggregation_access_changed: 'Aggregation access changed',
    group_by_plan_changed: 'GROUP BY plan changed',
    order_by_plan_changed: 'ORDER BY plan changed',
    plan_changed: 'Plan changed',
  };
  return map[ct] || ct;
}

function OperationCard({ op, variant }: { op: PlanOperation; variant: 'added' | 'removed' | 'old' | 'new' }) {
  const colors = {
    added: 'border-emerald-700 bg-emerald-900/20',
    removed: 'border-red-700 bg-red-900/20',
    old: 'border-red-800 bg-red-900/10',
    new: 'border-emerald-800 bg-emerald-900/10',
  };
  const icon = variant === 'added' ? <Plus className="w-3 h-3 text-emerald-400" />
    : variant === 'removed' ? <Minus className="w-3 h-3 text-red-400" />
    : null;

  return (
    <div className={`p-2 rounded border ${colors[variant]} text-xs space-y-1`}>
      <div className="flex items-center gap-1.5 font-mono">
        {icon}
        <span className="font-semibold text-dark-100">{op.operation || 'OTHER'}</span>
        {op.tableAlias && <span className="text-dark-300">{op.tableAlias}</span>}
        {op.indexName && (
          <span className="flex items-center gap-0.5 text-amber-400">
            <KeyRound className="w-3 h-3" /> {op.indexName}
          </span>
        )}
      </div>
      <div className="text-dark-400 font-mono text-[11px] break-all">{op.detail}</div>
      {op.astNodeKeys.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-0.5">
          {op.astNodeKeys.map((k) => {
            const meta = astNodeLabel(k);
            return (
              <span key={k} className={`inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-dark-800 ${meta.color}`}>
                {meta.icon}
                <span className="text-[10px]">{meta.label}</span>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function PlanDiffPanel() {
  const [snapshots, setSnapshots] = useState<PlanSnapshot[]>([]);
  const [oldId, setOldId] = useState<number | ''>('');
  const [newId, setNewId] = useState<number | ''>('');
  const [diff, setDiff] = useState<PlanDiff | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);

  const queryStructure = useQueryStore((s) => s.getQueryStructure());

  const loadSnapshots = useCallback(async () => {
    try {
      const data = await getPlanSnapshots();
      setSnapshots(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load snapshots');
    }
  }, []);

  useEffect(() => {
    loadSnapshots();
  }, [loadSnapshots]);

  const handleCapture = async () => {
    setCapturing(true);
    setError(null);
    try {
      await createPlanSnapshot({ query_structure: queryStructure, label: 'Manual capture' });
      await loadSnapshots();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to capture');
    } finally {
      setCapturing(false);
    }
  };

  const handleCompare = async () => {
    if (!oldId || !newId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await comparePlanSnapshots(Number(oldId), Number(newId));
      setDiff(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to compare');
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (s: string) => new Date(s).toLocaleString();

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 border-b border-dark-700 flex-shrink-0">
        <div className="flex items-center gap-2">
          <GitCompare className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-medium text-dark-200">Plan Comparison</span>
        </div>
        <button
          onClick={handleCapture}
          disabled={capturing}
          className="flex items-center gap-1 px-2 py-1 text-xs bg-purple-600 hover:bg-purple-500 text-white rounded transition-colors disabled:opacity-50"
        >
          {capturing ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
          Capture Current
        </button>
      </div>

      {error && (
        <div className="mx-3 mt-2 p-2 bg-red-900/30 border border-red-800 rounded text-xs text-red-300 flex-shrink-0">
          {error}
        </div>
      )}

      <div className="p-3 border-b border-dark-700 flex-shrink-0 space-y-2">
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <label className="text-[10px] uppercase text-dark-500 tracking-wide">Old (baseline)</label>
            <select
              value={oldId}
              onChange={(e) => setOldId(e.target.value ? Number(e.target.value) : '')}
              className="w-full mt-0.5 bg-dark-700 border border-dark-600 rounded px-2 py-1 text-xs text-dark-100 focus:outline-none focus:border-primary-500"
            >
              <option value="">Select snapshot…</option>
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  v{s.templateVersion || '?'} #{s.id} — {s.label || formatDate(s.createdAt)}
                </option>
              ))}
            </select>
          </div>
          <ArrowRight className="w-4 h-4 text-dark-500 mt-4 flex-shrink-0" />
          <div className="flex-1">
            <label className="text-[10px] uppercase text-dark-500 tracking-wide">New (candidate)</label>
            <select
              value={newId}
              onChange={(e) => setNewId(e.target.value ? Number(e.target.value) : '')}
              className="w-full mt-0.5 bg-dark-700 border border-dark-600 rounded px-2 py-1 text-xs text-dark-100 focus:outline-none focus:border-primary-500"
            >
              <option value="">Select snapshot…</option>
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  v{s.templateVersion || '?'} #{s.id} — {s.label || formatDate(s.createdAt)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <button
          onClick={handleCompare}
          disabled={!oldId || !newId || loading}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors disabled:opacity-50"
        >
          {loading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <GitCompare className="w-3 h-3" />}
          Compare Execution Plans
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {!diff ? (
          <div className="h-full flex flex-col items-center justify-center text-dark-500">
            <GitCompare className="w-10 h-10 mb-2 opacity-30" />
            <p className="text-sm">Select two snapshots to compare</p>
            <p className="text-xs mt-1">Changes are mapped to AST nodes, not SQL line numbers</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-2">
              <div className="p-2 bg-dark-800 rounded border border-dark-700 text-center">
                <div className="text-lg font-bold text-emerald-400">{diff.summary.added}</div>
                <div className="text-[10px] uppercase text-dark-500 tracking-wide">Added</div>
              </div>
              <div className="p-2 bg-dark-800 rounded border border-dark-700 text-center">
                <div className="text-lg font-bold text-red-400">{diff.summary.removed}</div>
                <div className="text-[10px] uppercase text-dark-500 tracking-wide">Removed</div>
              </div>
              <div className="p-2 bg-dark-800 rounded border border-dark-700 text-center">
                <div className="text-lg font-bold text-amber-400">{diff.summary.changed}</div>
                <div className="text-[10px] uppercase text-dark-500 tracking-wide">Changed</div>
              </div>
            </div>

            {!diff.summary.hasChanges && (
              <div className="p-4 bg-emerald-900/20 border border-emerald-800 rounded text-center">
                <p className="text-sm text-emerald-300 font-medium">No semantic plan changes</p>
                <p className="text-xs text-emerald-500 mt-1">
                  Non-semantic differences (node IDs, formatting) do not produce a change set
                </p>
              </div>
            )}

            {diff.astChanges.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-dark-300 uppercase tracking-wide mb-2">
                  AST-Level Changes
                </h4>
                <div className="space-y-1.5">
                  {diff.astChanges.map((c, i) => {
                    const meta = astNodeLabel(c.astNodeKey);
                    return (
                      <div key={i} className="p-2 bg-dark-800 rounded border border-dark-700">
                        <div className={`flex items-center gap-1.5 ${meta.color}`}>
                          {meta.icon}
                          <span className="text-xs font-medium">{meta.label}</span>
                        </div>
                        <div className="mt-1 text-xs text-dark-300">
                          {changeTypeLabel(c.changeType)}
                        </div>
                        <div className="mt-1 flex items-center gap-2 text-[11px] font-mono">
                          <span className="text-red-400 line-through">{c.oldValue}</span>
                          <ArrowRight className="w-3 h-3 text-dark-500" />
                          <span className="text-emerald-400">{c.newValue}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {diff.changed.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-dark-300 uppercase tracking-wide mb-2">
                  Changed Access Paths
                </h4>
                <div className="space-y-2">
                  {diff.changed.map((c, i) => (
                    <div key={i} className="grid grid-cols-2 gap-2">
                      <div>
                        <div className="text-[10px] uppercase text-red-400 tracking-wide mb-0.5">Before</div>
                        <OperationCard op={c.old} variant="old" />
                      </div>
                      <div>
                        <div className="text-[10px] uppercase text-emerald-400 tracking-wide mb-0.5">After</div>
                        <OperationCard op={c.new} variant="new" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {diff.added.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wide mb-2">
                  Added Operations
                </h4>
                <div className="space-y-1.5">
                  {diff.added.map((op, i) => <OperationCard key={i} op={op} variant="added" />)}
                </div>
              </div>
            )}

            {diff.removed.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-red-400 uppercase tracking-wide mb-2">
                  Removed Operations
                </h4>
                <div className="space-y-1.5">
                  {diff.removed.map((op, i) => <OperationCard key={i} op={op} variant="removed" />)}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
