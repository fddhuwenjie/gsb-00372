import { X } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { ChartType } from '@/types';

interface ChartConfigProps {
  onClose: () => void;
}

const CHART_TYPES: { value: ChartType; label: string; description: string }[] = [
  { value: 'line', label: 'Line', description: 'Time series & trends' },
  { value: 'bar', label: 'Bar', description: 'Comparisons & categories' },
  { value: 'pie', label: 'Pie', description: 'Proportions' },
  { value: 'scatter', label: 'Scatter', description: 'Correlations' },
];

export default function ChartConfig({ onClose }: ChartConfigProps) {
  const queryResult = useQueryStore((state) => state.queryResult);
  const chartConfig = useQueryStore((state) => state.chartConfig);
  const setChartConfig = useQueryStore((state) => state.setChartConfig);

  if (!queryResult) return null;

  const columns = queryResult.columns;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-dark-800 rounded-lg border border-dark-600 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-dark-700">
          <h2 className="text-lg font-semibold text-dark-100">Chart Settings</h2>
          <button
            onClick={onClose}
            className="p-1 text-dark-400 hover:text-dark-200 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <label className="block text-sm font-medium text-dark-200 mb-2">
              Chart Type
            </label>
            <div className="grid grid-cols-2 gap-2">
              {CHART_TYPES.map((type) => (
                <button
                  key={type.value}
                  onClick={() => setChartConfig({ ...chartConfig!, type: type.value })}
                  className={`p-3 rounded border text-left transition-colors ${
                    chartConfig?.type === type.value
                      ? 'border-primary-500 bg-primary-900/30'
                      : 'border-dark-600 hover:border-dark-500 bg-dark-700'
                  }`}
                >
                  <div className="font-medium text-dark-100">{type.label}</div>
                  <div className="text-xs text-dark-400 mt-0.5">{type.description}</div>
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-dark-200 mb-1">
              X Axis Field
            </label>
            <select
              value={chartConfig?.xField || ''}
              onChange={(e) => setChartConfig({ ...chartConfig!, xField: e.target.value })}
              className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 focus:outline-none focus:border-primary-500"
            >
              <option value="">Select field...</option>
              {columns.map((col) => (
                <option key={col.name} value={col.name}>
                  {col.name} ({col.type})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-dark-200 mb-1">
              Y Axis Field
            </label>
            <select
              value={chartConfig?.yField || ''}
              onChange={(e) => setChartConfig({ ...chartConfig!, yField: e.target.value })}
              className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 focus:outline-none focus:border-primary-500"
            >
              <option value="">Select field...</option>
              {columns.map((col) => (
                <option key={col.name} value={col.name}>
                  {col.name} ({col.type})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-dark-200 mb-1">
              Series Field (optional)
            </label>
            <select
              value={chartConfig?.seriesField || ''}
              onChange={(e) => setChartConfig({ ...chartConfig!, seriesField: e.target.value || undefined })}
              className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 focus:outline-none focus:border-primary-500"
            >
              <option value="">None</option>
              {columns.map((col) => (
                <option key={col.name} value={col.name}>
                  {col.name} ({col.type})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-dark-200 mb-1">
              Title (optional)
            </label>
            <input
              type="text"
              value={chartConfig?.title || ''}
              onChange={(e) => setChartConfig({ ...chartConfig!, title: e.target.value || undefined })}
              placeholder="Chart title"
              className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 placeholder-dark-500 focus:outline-none focus:border-primary-500"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-dark-700">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
