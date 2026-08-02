import type { TemplateParameter } from '@/types';

interface ParamFormProps {
  parameters: TemplateParameter[];
  values: Record<string, any>;
  onChange: (name: string, value: any) => void;
}

/**
 * Renders a typed input per declared parameter. Instantiation only ever sends
 * these values back to the server -- the query structure itself is fixed by the
 * template, so parameters can never alter SQL shape.
 */
export default function ParamForm({ parameters, values, onChange }: ParamFormProps) {
  if (parameters.length === 0) {
    return <p className="text-sm text-dark-500">This template has no parameters.</p>;
  }

  return (
    <div className="space-y-3">
      {parameters.map((p) => (
        <div key={p.name} className="flex flex-col gap-1">
          <label className="text-xs text-dark-300 flex items-center gap-1">
            <span className="font-medium text-dark-100">{p.label || p.name}</span>
            <span className="text-dark-500">({p.type}{p.type === 'list' ? ` of ${p.itemType || 'string'}` : ''})</span>
            {p.required && <span className="text-red-400">*</span>}
          </label>
          <ParamInput param={p} value={values[p.name]} onChange={(v) => onChange(p.name, v)} />
        </div>
      ))}
    </div>
  );
}

function ParamInput({
  param,
  value,
  onChange,
}: {
  param: TemplateParameter;
  value: any;
  onChange: (value: any) => void;
}) {
  const cls =
    'bg-dark-700 border border-dark-600 rounded px-2 py-1 text-sm text-dark-200 focus:outline-none focus:border-primary-500';

  if (param.type === 'boolean') {
    return (
      <input
        type="checkbox"
        checked={!!value}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 accent-primary-500"
      />
    );
  }

  if (param.type === 'date') {
    return (
      <input
        type="date"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        className={cls}
      />
    );
  }

  if (param.type === 'integer' || param.type === 'number') {
    return (
      <input
        type="number"
        step={param.type === 'integer' ? '1' : 'any'}
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === '') {
            onChange(undefined);
          } else {
            onChange(param.type === 'integer' ? parseInt(raw, 10) : parseFloat(raw));
          }
        }}
        className={cls}
        placeholder={param.type}
      />
    );
  }

  if (param.type === 'list') {
    const text = Array.isArray(value) ? value.join(', ') : '';
    const itemType = param.itemType || 'string';
    return (
      <input
        type="text"
        value={text}
        placeholder="comma,separated,values"
        onChange={(e) => {
          const items = e.target.value
            .split(',')
            .map((v) => v.trim())
            .filter((v) => v !== '')
            .map((v) => {
              if (itemType === 'integer') return parseInt(v, 10);
              if (itemType === 'number') return parseFloat(v);
              return v;
            });
          onChange(items);
        }}
        className={cls}
      />
    );
  }

  // string (default)
  return (
    <input
      type="text"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
      className={cls}
      placeholder={param.name}
    />
  );
}
