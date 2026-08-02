import { useMemo, useState } from 'react';
import { X, FileCode } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import { useTemplateStore } from '@/store/templateStore';
import type {
  ParamType, ParameterizeSpec, WhereCondition, WhereClause, WhereNode,
} from '@/types';
import { isWhereClause, isWhereCondition } from '@/types';

interface SaveTemplateDialogProps {
  onClose: () => void;
}

interface Candidate {
  key: string;              // unique key for UI
  label: string;            // human description
  target: ParameterizeSpec['target'];
  suggestedType: ParamType;
  suggestedItemType?: ParamType;
}

/** Walk the WHERE/HAVING tree and collect leaf clauses that carry a value
 *  (i.e. can be parameterized). IS NULL / EXISTS leaves are skipped. */
function collectFilterLeaves(
  node: WhereNode | null,
  aliasOf: (tableId: string) => string,
  out: Candidate[]
) {
  if (!node) return;
  if (isWhereCondition(node)) {
    (node as WhereCondition).children.forEach((c) => collectFilterLeaves(c, aliasOf, out));
    return;
  }
  if (isWhereClause(node)) {
    const clause = node as WhereClause;
    if (['IS NULL', 'IS NOT NULL', 'EXISTS', 'NOT EXISTS'].includes(clause.cmp)) return;
    if (clause.subquery) return;
    const isList = clause.cmp === 'IN' || clause.cmp === 'NOT IN';
    out.push({
      key: clause.id,
      label: `${aliasOf(clause.tableId)}.${clause.columnName} ${clause.cmp}`,
      target: { kind: 'filter', clauseId: clause.id },
      suggestedType: isList ? 'list' : 'string',
      suggestedItemType: isList ? 'string' : undefined,
    });
  }
}

const PARAM_TYPES: ParamType[] = ['string', 'integer', 'number', 'date', 'boolean', 'list'];

export default function SaveTemplateDialog({ onClose }: SaveTemplateDialogProps) {
  const getQueryStructure = useQueryStore((s) => s.getQueryStructure);
  const tables = useQueryStore((s) => s.tables);
  const saveAsTemplate = useTemplateStore((s) => s.saveAsTemplate);

  const structure = useMemo(() => getQueryStructure(), [getQueryStructure]);
  const aliasOf = (tableId: string) => tables.find((t) => t.id === tableId)?.alias || tableId;

  const candidates = useMemo(() => {
    const out: Candidate[] = [];
    collectFilterLeaves(structure.where, aliasOf, out);
    collectFilterLeaves(structure.having ?? null, aliasOf, out);
    out.push({ key: '__limit__', label: 'LIMIT (page size)', target: { kind: 'limit' }, suggestedType: 'integer' });
    out.push({ key: '__offset__', label: 'OFFSET (page start)', target: { kind: 'offset' }, suggestedType: 'integer' });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structure]);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selected, setSelected] = useState<Record<string, {
    on: boolean; name: string; type: ParamType; itemType: ParamType; required: boolean; def: string;
  }>>(() => {
    const init: Record<string, any> = {};
    for (const c of candidates) {
      // Suggest a param name: alias_column for filters, limit/offset for paging.
      let suggested = 'param';
      if (c.key === '__limit__') suggested = 'page_size';
      else if (c.key === '__offset__') suggested = 'page_offset';
      else suggested = c.label.split(' ')[0].replace(/\./g, '_');
      init[c.key] = {
        on: false,
        name: suggested,
        type: c.suggestedType,
        itemType: c.suggestedItemType || 'string',
        required: false,
        def: '',
      };
    }
    return init;
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const toggle = (key: string, patch: Partial<{ on: boolean; name: string; type: ParamType; itemType: ParamType; required: boolean; def: string }>) => {
    setSelected((s) => ({ ...s, [key]: { ...s[key], ...patch } }));
  };

  const parseDefault = (raw: string, type: ParamType, itemType: ParamType): any => {
    if (raw === '') return undefined;
    if (type === 'integer') return parseInt(raw, 10);
    if (type === 'number') return parseFloat(raw);
    if (type === 'boolean') return raw === 'true';
    if (type === 'list') {
      return raw.split(',').map((v) => v.trim()).filter(Boolean).map((v) =>
        itemType === 'integer' ? parseInt(v, 10) : itemType === 'number' ? parseFloat(v) : v
      );
    }
    return raw;
  };

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Template name is required');
      return;
    }
    const specs: ParameterizeSpec[] = [];
    const seen = new Set<string>();
    for (const c of candidates) {
      const s = selected[c.key];
      if (!s?.on) continue;
      const pname = s.name.trim();
      if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(pname)) {
        setError(`Invalid parameter name: ${pname || '(empty)'}`);
        return;
      }
      if (seen.has(pname)) {
        setError(`Duplicate parameter name: ${pname}`);
        return;
      }
      seen.add(pname);
      const spec: ParameterizeSpec = { name: pname, type: s.type, target: c.target, required: s.required };
      if (s.type === 'list') spec.itemType = s.itemType;
      const def = parseDefault(s.def, s.type, s.itemType);
      if (def !== undefined) spec.default = def;
      specs.push(spec);
    }
    if (specs.length === 0) {
      setError('Select at least one filter or pagination value to parameterize');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await saveAsTemplate(name.trim(), description.trim(), structure, specs);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save template');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-dark-800 rounded-lg border border-dark-600 w-full max-w-2xl shadow-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-dark-700">
          <h2 className="text-lg font-semibold text-dark-100 flex items-center gap-2">
            <FileCode className="w-5 h-5 text-primary-400" />
            Save as Template
          </h2>
          <button onClick={onClose} className="p-1 text-dark-400 hover:text-dark-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4 overflow-y-auto">
          {error && (
            <div className="p-3 bg-red-900/30 border border-red-800 rounded text-sm text-red-300">{error}</div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-dark-200 mb-1">Name *</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 focus:outline-none focus:border-primary-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-dark-200 mb-1">Description</label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 focus:outline-none focus:border-primary-500"
              />
            </div>
          </div>

          <div>
            <p className="text-sm font-medium text-dark-200 mb-2">
              Parameterize values (structure stays fixed)
            </p>
            <div className="space-y-2">
              {candidates.map((c) => {
                const s = selected[c.key];
                return (
                  <div key={c.key} className="p-2 bg-dark-900 rounded border border-dark-700">
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={s.on}
                        onChange={(e) => toggle(c.key, { on: e.target.checked })}
                        className="w-4 h-4 accent-primary-500"
                      />
                      <span className="text-sm text-dark-200 flex-1">{c.label}</span>
                    </div>
                    {s.on && (
                      <div className="mt-2 flex flex-wrap items-center gap-2 pl-6">
                        <input
                          type="text"
                          value={s.name}
                          placeholder="param_name"
                          onChange={(e) => toggle(c.key, { name: e.target.value })}
                          className="px-2 py-1 text-xs bg-dark-700 border border-dark-600 rounded text-dark-200 w-32"
                        />
                        <select
                          value={s.type}
                          onChange={(e) => toggle(c.key, { type: e.target.value as ParamType })}
                          className="px-2 py-1 text-xs bg-dark-700 border border-dark-600 rounded text-dark-200"
                        >
                          {PARAM_TYPES.map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                        {s.type === 'list' && (
                          <select
                            value={s.itemType}
                            onChange={(e) => toggle(c.key, { itemType: e.target.value as ParamType })}
                            className="px-2 py-1 text-xs bg-dark-700 border border-dark-600 rounded text-dark-200"
                          >
                            {PARAM_TYPES.filter((t) => t !== 'list').map((t) => (
                              <option key={t} value={t}>{t}</option>
                            ))}
                          </select>
                        )}
                        <input
                          type="text"
                          value={s.def}
                          placeholder="default"
                          onChange={(e) => toggle(c.key, { def: e.target.value })}
                          className="px-2 py-1 text-xs bg-dark-700 border border-dark-600 rounded text-dark-200 w-24"
                        />
                        <label className="flex items-center gap-1 text-xs text-dark-300">
                          <input
                            type="checkbox"
                            checked={s.required}
                            onChange={(e) => toggle(c.key, { required: e.target.checked })}
                            className="w-3.5 h-3.5 accent-primary-500"
                          />
                          required
                        </label>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-dark-700">
          <button onClick={onClose} className="px-4 py-2 text-sm text-dark-300 hover:text-dark-100">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-primary-600 hover:bg-primary-500 text-white rounded disabled:opacity-50"
          >
            <FileCode className="w-4 h-4" />
            {saving ? 'Saving...' : 'Save Template'}
          </button>
        </div>
      </div>
    </div>
  );
}
