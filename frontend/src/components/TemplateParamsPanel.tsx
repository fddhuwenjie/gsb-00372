import { useState, useEffect } from 'react';
import { Play, Settings2, AlertCircle } from 'lucide-react';
import type { TemplateParameter, TemplateInstantiateResult } from '@/types';

interface TemplateParamsPanelProps {
  parameters: TemplateParameter[];
  onInstantiate: (values: Record<string, any>) => Promise<void>;
  result?: TemplateInstantiateResult | null;
  loading?: boolean;
  error?: string | null;
}

function defaultFor(param: TemplateParameter): any {
  if (param.default !== undefined) return param.default;
  if (param.type.endsWith('_list')) return [];
  if (param.type === 'boolean') return false;
  if (param.type === 'integer' || param.type === 'number') return '';
  return '';
}

export default function TemplateParamsPanel({
  parameters,
  onInstantiate,
  result,
  loading,
  error,
}: TemplateParamsPanelProps) {
  const [values, setValues] = useState<Record<string, any>>({});

  useEffect(() => {
    const initial: Record<string, any> = {};
    for (const p of parameters) {
      initial[p.name] = defaultFor(p);
    }
    setValues(initial);
  }, [parameters]);

  const setValue = (name: string, value: any) => {
    setValues((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onInstantiate(values);
  };

  const renderInput = (param: TemplateParameter) => {
    const value = values[param.name];
    const baseClass =
      'w-full bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-100 focus:outline-none focus:border-primary-500';

    if (param.options && param.options.length > 0) {
      return (
        <select
          className={baseClass}
          value={value ?? ''}
          onChange={(e) => setValue(param.name, e.target.value)}
        >
          <option value="">-- select --</option>
          {param.options.map((opt) => (
            <option key={String(opt.value)} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      );
    }

    if (param.type === 'boolean') {
      return (
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => setValue(param.name, e.target.checked)}
          className="w-4 h-4"
        />
      );
    }

    if (param.type === 'date') {
      return (
        <input
          type="date"
          className={baseClass}
          value={value ?? ''}
          onChange={(e) => setValue(param.name, e.target.value)}
        />
      );
    }

    if (param.type === 'datetime') {
      return (
        <input
          type="datetime-local"
          className={baseClass}
          value={value ?? ''}
          onChange={(e) => setValue(param.name, e.target.value)}
        />
      );
    }

    if (param.type === 'integer' || param.type === 'number') {
      return (
        <input
          type="number"
          className={baseClass}
          value={value ?? ''}
          step={param.type === 'number' ? 'any' : '1'}
          onChange={(e) =>
            setValue(
              param.name,
              e.target.value === ''
                ? ''
                : param.type === 'integer'
                ? parseInt(e.target.value, 10)
                : parseFloat(e.target.value),
            )
          }
        />
      );
    }

    if (param.type.endsWith('_list')) {
      return (
        <input
          type="text"
          className={baseClass}
          placeholder="comma-separated values"
          value={Array.isArray(value) ? value.join(', ') : ''}
          onChange={(e) =>
            setValue(
              param.name,
              e.target.value
                .split(',')
                .map((v) => v.trim())
                .filter(Boolean),
            )
          }
        />
      );
    }

    return (
      <input
        type="text"
        className={baseClass}
        value={value ?? ''}
        onChange={(e) => setValue(param.name, e.target.value)}
      />
    );
  };

  return (
    <form onSubmit={handleSubmit} className="border-t border-dark-700">
      <div className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <Settings2 className="w-4 h-4 text-primary-400" />
          <span className="font-medium text-dark-200">Template Parameters</span>
        </div>

        {parameters.length === 0 ? (
          <p className="text-sm text-dark-500">
            This template has no parameters.
          </p>
        ) : (
          <div className="space-y-3">
            {parameters.map((param) => (
              <div key={param.name}>
                <label className="flex items-center gap-1 text-xs text-dark-300 mb-1">
                  {param.label || param.name}
                  {param.required && (
                    <span className="text-red-400">*</span>
                  )}
                  <span className="ml-auto text-dark-500">{param.type}</span>
                </label>
                {renderInput(param)}
                {param.help && (
                  <p className="text-xs text-dark-500 mt-1">{param.help}</p>
                )}
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="mt-3 flex items-start gap-2 p-2 bg-red-900/20 border border-red-800 rounded text-xs text-red-300">
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span className="break-all">{error}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="mt-4 w-full flex items-center justify-center gap-2 px-3 py-2 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded transition-colors disabled:opacity-50"
        >
          {loading ? (
            'Running...'
          ) : (
            <>
              <Play className="w-3.5 h-3.5" />
              Execute Template
            </>
          )}
        </button>
      </div>

      {result && result.rows && (
        <div className="px-4 pb-4">
          <div className="text-xs text-dark-400 mb-2">
            {result.rowCount} rows · {result.executionTime?.toFixed(1)} ms
          </div>
          <div className="max-h-64 overflow-auto bg-dark-900 rounded border border-dark-700">
            <table className="w-full text-xs">
              <thead className="bg-dark-800 sticky top-0">
                <tr>
                  {result.columns?.map((col, i) => (
                    <th
                      key={i}
                      className="px-2 py-1 text-left text-dark-200 border-b border-dark-700"
                    >
                      {col.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.slice(0, 50).map((row, ri) => (
                  <tr key={ri} className="border-b border-dark-800">
                    {row.map((cell, ci) => (
                      <td key={ci} className="px-2 py-1 text-dark-300 font-mono">
                        {cell === null ? (
                          <span className="text-dark-500 italic">NULL</span>
                        ) : (
                          String(cell)
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </form>
  );
}
