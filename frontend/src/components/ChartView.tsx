import { useRef, useEffect, useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { Download, Settings } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { ChartConfig, ChartType, QueryResult, ResultColumn } from '@/types';

interface ChartViewProps {
  result: QueryResult;
  onConfigClick: () => void;
}

function suggestChartType(columns: ResultColumn[]): ChartConfig {
  const numericCols = columns.filter(c => 
    ['INTEGER', 'NUMERIC', 'FLOAT', 'INT', 'DECIMAL'].includes(c.type.toUpperCase())
  );
  const stringCols = columns.filter(c => 
    ['STRING', 'TEXT', 'VARCHAR', 'CHAR'].includes(c.type.toUpperCase())
  );
  const dateCols = columns.filter(c => 
    ['DATE', 'DATETIME', 'TIMESTAMP', 'TIME'].includes(c.type.toUpperCase())
  );

  if (dateCols.length > 0 && numericCols.length > 0) {
    return {
      type: 'line',
      xField: dateCols[0].name,
      yField: numericCols[0].name,
      seriesField: stringCols[0]?.name,
    };
  }

  if (stringCols.length > 0 && numericCols.length > 0) {
    if (numericCols.length >= 2) {
      return {
        type: 'scatter',
        xField: numericCols[0].name,
        yField: numericCols[1].name,
        seriesField: stringCols[0].name,
      };
    }
    return {
      type: 'bar',
      xField: stringCols[0].name,
      yField: numericCols[0].name,
    };
  }

  if (numericCols.length >= 2) {
    return {
      type: 'scatter',
      xField: numericCols[0].name,
      yField: numericCols[1].name,
    };
  }

  if (numericCols.length > 0) {
    return {
      type: 'bar',
      xField: columns[0].name,
      yField: numericCols[0].name,
    };
  }

  return {
    type: 'bar',
    xField: columns[0]?.name || '',
    yField: columns[1]?.name || '',
  };
}

export default function ChartView({ result, onConfigClick }: ChartViewProps) {
  const chartRef = useRef<ReactECharts>(null);
  const chartConfig = useQueryStore((state) => state.chartConfig);
  const setChartConfig = useQueryStore((state) => state.setChartConfig);

  const config = useMemo(() => {
    if (chartConfig) return chartConfig;
    if (result.columns.length === 0) return null;
    return suggestChartType(result.columns);
  }, [chartConfig, result.columns]);

  useEffect(() => {
    if (!chartConfig && result.columns.length > 0) {
      const suggested = suggestChartType(result.columns);
      setChartConfig(suggested);
    }
  }, [result.columns, chartConfig, setChartConfig]);

  const option = useMemo(() => {
    if (!config || !config.xField || !config.yField) {
      return {};
    }

    const xIdx = result.columns.findIndex(c => c.name === config.xField);
    const yIdx = result.columns.findIndex(c => c.name === config.yField);
    const seriesIdx = config.seriesField ? result.columns.findIndex(c => c.name === config.seriesField) : -1;

    if (xIdx === -1 || yIdx === -1) {
      return {};
    }

    if (config.type === 'pie') {
      const data = result.rows.map(row => ({
        name: String(row[xIdx]),
        value: Number(row[yIdx]) || 0,
      }));
      return {
        title: { text: config.title, left: 'center', textStyle: { color: '#e5e7eb', fontSize: 14 } },
        tooltip: { trigger: 'item' },
        legend: { bottom: '5%', textStyle: { color: '#9ca3af' } },
        series: [{
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          itemStyle: { borderRadius: 6, borderColor: '#1e293b', borderWidth: 2 },
          label: { show: false },
          emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
          data,
        }],
        backgroundColor: 'transparent',
      };
    }

    const series = [];
    if (seriesIdx >= 0) {
      const groups = new Map<string, { name: string; data: [any, number][] }>();
      result.rows.forEach(row => {
        const key = String(row[seriesIdx]);
        if (!groups.has(key)) {
          groups.set(key, { name: key, data: [] });
        }
        groups.get(key)!.data.push([row[xIdx], Number(row[yIdx]) || 0]);
      });
      groups.forEach(g => series.push({ name: g.name, type: config.type, data: g.data, smooth: config.type === 'line' }));
    } else {
      series.push({
        name: config.yField,
        type: config.type,
        data: result.rows.map(row => [row[xIdx], Number(row[yIdx]) || 0]),
        smooth: config.type === 'line',
        itemStyle: { color: '#3b82f6' },
      });
    }

    return {
      title: { text: config.title, left: 'center', textStyle: { color: '#e5e7eb', fontSize: 14 } },
      tooltip: { trigger: config.type === 'scatter' ? 'item' : 'axis' },
      legend: series.length > 1 ? { top: '10%', textStyle: { color: '#9ca3af' } } : undefined,
      grid: { left: '3%', right: '4%', bottom: '3%', top: '20%', containLabel: true },
      xAxis: {
        type: 'category',
        name: config.xField,
        nameTextStyle: { color: '#9ca3af' },
        axisLine: { lineStyle: { color: '#475569' } },
        axisLabel: { color: '#9ca3af' },
      },
      yAxis: {
        type: 'value',
        name: config.yField,
        nameTextStyle: { color: '#9ca3af' },
        axisLine: { lineStyle: { color: '#475569' } },
        axisLabel: { color: '#9ca3af' },
        splitLine: { lineStyle: { color: '#334155' } },
      },
      series,
      backgroundColor: 'transparent',
    };
  }, [config, result]);

  const handleDownload = (format: 'png' | 'svg') => {
    if (chartRef.current) {
      const chart = chartRef.current.getEchartsInstance();
      const url = chart.getDataURL({
        type: format,
        pixelRatio: 2,
        backgroundColor: '#1e293b',
      });
      const link = document.createElement('a');
      link.download = `chart.${format}`;
      link.href = url;
      link.click();
    }
  };

  if (!config || !config.xField || !config.yField) {
    return (
      <div className="h-full flex items-center justify-center text-dark-400 text-sm">
        Configure chart fields to visualize data
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-dark-400">
            {config.type.toUpperCase()} Chart
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onConfigClick}
            className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-700"
            title="Chart Settings"
          >
            <Settings className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleDownload('png')}
            className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-700"
            title="Download PNG"
          >
            <Download className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleDownload('svg')}
            className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-700"
            title="Download SVG"
          >
            <Download className="w-4 h-4" />
            <span className="text-[10px] ml-0.5">SVG</span>
          </button>
        </div>
      </div>
      <div className="flex-1 min-h-0">
        <ReactECharts
          ref={chartRef}
          option={option}
          style={{ height: '100%', width: '100%' }}
          notMerge={true}
          lazyUpdate={true}
        />
      </div>
    </div>
  );
}
