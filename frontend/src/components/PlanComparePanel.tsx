import { useMemo, useState } from 'react';
import { GitCompare, ArrowRight, Plus, Minus, RefreshCw } from 'lucide-react';
import type { QueryTemplate, PlanComparison, PlanChange } from '@/types';
import { compareTemplatePlans } from '@/services/api';
import ParamForm from './ParamForm';
import { useTemplateStore } from '@/store/templateStore';

interface PlanComparePanelProps {
  template: QueryTemplate;
}

/** Render one located change in AST terms (never SQL line numbers). */
function describeChange(ch: PlanChange): string {
  const n = ch.node || ch.to || ch.from || {};
  switch (ch.kind) {
    case 'join': {
      if (ch.change === 'modified') {
        return `JOIN ${ch.from?.a}↔${ch.from?.b}: ${ch.from?.type} → ${ch.to?.type}`;
      }
      return `JOIN ${n.type} ${n.a}.${n.aColumn} ↔ ${n.b}.${n.bColumn}`;
    }
    case 'filter':
      return `Filter ${n.table}.${n.column} ${n.cmp}${n.function ? ` [${n.function}]` : ''}`;
    case 'aggregation':
      return `Aggregation ${n.function}(${n.table}.${n.column})`;
    case 'field':
      return `Field ${n.table}.${n.column}`;
    case 'orderBy':
      return `Order by ${n.table}.${n.column} ${n.direction}`;
    case 'access': {
      if (ch.change === 'modified') {
        const f = ch.from, t = ch.to;
        const fa = f.isFullScan ? 'full scan' : f.index ? `index ${f.index}` : f.access;
        const ta = t.isFullScan ? 'full scan' : t.index ? `index ${t.index}` : t.access;
        return `Access ${ch.tableRef}: ${fa} → ${ta}`;
      }
      return `Access ${n.tableRef}: ${n.isFullScan ? 'full scan' : n.index ? `index ${n.index}` : n.access}`;
    }
    case 'planFlag':
      return `Plan flag ${ch.flag}: ${ch.from} → ${ch.to}`;
    default:
      return JSON.stringify(ch);
  }
}

const KIND_COLORS: Record<string, string> = {
  join: 'text-sky-300 bg-sky-900/30 border-sky-800',
  filter: 'text-amber-300 bg-amber-900/30 border-amber-800',
  aggregation: 'text-purple-300 bg-purple-900/30 border-purple-800',
  field: 'text-dark-300 bg-dark-700/50 border-dark-600',
  orderBy: 'text-teal-300 bg-teal-900/30 border-teal-800',
  access: 'text-emerald-300 bg-emerald-900/30 border-emerald-800',
  planFlag: 'text-rose-300 bg-rose-900/30 border-rose-800',
};

function ChangeIcon({ change }: { change: PlanChange['change'] }) {
  if (change === 'added') return <Plus className="w-3.5 h-3.5 text-emerald-400" />;
  if (change === 'removed') return <Minus className="w-3.5 h-3.5 text-red-400" />;
  return <ArrowRight className="w-3.5 h-3.5 text-amber-400" />;
}

export default function PlanComparePanel({ template }: PlanComparePanelProps) {
  const versions = template.versions || [];
  const [versionA, setVersionA] = useState<number>(versions[0]?.version ?? 1);
  const [versionB, setVersionB] = useState<number>(template.current_version);
  const [values, setValues] = useState<Record<string, any>>({});
  const [comparison, setComparison] = useState<PlanComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const paramValues = useTemplateStore((s) => s.paramValues);

  // Union of parameters across both versions so the form can supply values for
  // whichever version needs them (params only feed execution, never persisted).
  const params = useMemo(() => {
    const byName = new Map<string, any>();
    for (const v of versions) {
      for (const p of v.parameters) if (!byName.has(p.name)) byName.set(p.name, p);
    }
    for (const p of template.parameters) if (!byName.has(p.name)) byName.set(p.name, p);
    return Array.from(byName.values());
  }, [versions, template.parameters]);

  const runCompare = async () => {
    setLoading(true);
    setError(null);
    try {
      const merged = { ...paramValues, ...values };
      const result = await compareTemplatePlans(template.id, versionA, versionB, merged, true);
      setComparison(result);
    } catch (err: any) {
      setError(err?.message || 'Failed to compare');
      setComparison(null);
    } finally {
      setLoading(false);
    }
  };

  const allChanges = comparison ? [...comparison.astChanges, ...comparison.planChanges] : [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm text-dark-200">
        <GitCompare className="w-4 h-4 text-primary-400" />
        <span className="font-medium">Compare versions</span>
        <select
          value={versionA}
          onChange={(e) => setVersionA(parseInt(e.target.value, 10))}
          className="bg-dark-700 border border-dark-600 rounded px-2 py-1 text-xs text-dark-200"
        >
          {versions.map((v) => (
            <option key={v.version} value={v.version}>v{v.version}</option>
          ))}
        </select>
        <ArrowRight className="w-3.5 h-3.5 text-dark-500" />
        <select
          value={versionB}
          onChange={(e) => setVersionB(parseInt(e.target.value, 10))}
          className="bg-dark-700 border border-dark-600 rounded px-2 py-1 text-xs text-dark-200"
        >
          {versions.map((v) => (
            <option key={v.version} value={v.version}>v{v.version}</option>
          ))}
        </select>
        <button
          onClick={runCompare}
          disabled={loading}
          className="ml-auto flex items-center gap-1.5 px-3 py-1 bg-primary-600 hover:bg-primary-500 text-white text-xs rounded disabled:opacity-50"
        >
          {loading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <GitCompare className="w-3.5 h-3.5" />}
          Compare
        </button>
      </div>

      {params.length > 0 && (
        <div className="p-3 bg-dark-800 rounded border border-dark-700">
          <p className="text-xs text-dark-400 mb-2">Sample parameter values (types only are stored)</p>
          <ParamForm
            parameters={params}
            values={{ ...paramValues, ...values }}
            onChange={(name, v) => setValues((s) => ({ ...s, [name]: v }))}
          />
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-900/20 border border-red-800 rounded text-sm text-red-300">{error}</div>
      )}

      {comparison && (
        <div className="space-y-3">
          <div className={`p-3 rounded border text-sm ${
            comparison.semanticallyEqual
              ? 'bg-emerald-900/20 border-emerald-800 text-emerald-300'
              : 'bg-amber-900/20 border-amber-800 text-amber-300'
          }`}>
            {comparison.semanticallyEqual
              ? 'Semantically identical — same AST hash, no version difference.'
              : `${comparison.changeCount} located change(s) between v${comparison.versionA} and v${comparison.versionB}.`}
          </div>

          {/* Cost + param-type summary */}
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="p-2 bg-dark-800 rounded border border-dark-700">
              <div className="text-dark-400 mb-1">Rows</div>
              <div className="text-dark-200 font-mono">
                {comparison.result.rowCountA} → {comparison.result.rowCountB}
                {comparison.result.rowCountDelta != null && (
                  <span className={comparison.result.rowCountDelta === 0 ? 'text-dark-500' : 'text-amber-400'}>
                    {' '}({comparison.result.rowCountDelta >= 0 ? '+' : ''}{comparison.result.rowCountDelta})
                  </span>
                )}
              </div>
            </div>
            <div className="p-2 bg-dark-800 rounded border border-dark-700">
              <div className="text-dark-400 mb-1">Duration (ms)</div>
              <div className="text-dark-200 font-mono">
                {comparison.result.durationMsA} → {comparison.result.durationMsB}
              </div>
            </div>
          </div>

          {allChanges.length === 0 ? (
            <p className="text-sm text-dark-500">No structural or plan differences.</p>
          ) : (
            <ul className="space-y-1.5">
              {allChanges.map((ch, i) => (
                <li
                  key={i}
                  className={`flex items-center gap-2 px-3 py-2 rounded border text-xs ${KIND_COLORS[ch.kind] || KIND_COLORS.field}`}
                >
                  <ChangeIcon change={ch.change} />
                  <span className="uppercase text-[10px] font-semibold opacity-70 w-20">{ch.kind}</span>
                  <span className="font-mono">{describeChange(ch)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
