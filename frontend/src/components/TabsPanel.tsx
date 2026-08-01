import { useState } from 'react';
import { Table, BarChart3, History, GitBranch, Share2, Download, Play } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { TabType, ResultViewMode } from '@/types';
import ResultPanel from './ResultPanel';
import ExplainPlan from './ExplainPlan';
import ChartView from './ChartView';
import ChartConfig from './ChartConfig';
import { exportQuery } from '@/services/api';

const TABS: { id: TabType; label: string; icon: React.ReactNode }[] = [
  { id: 'result', label: 'Results', icon: <Table className="w-4 h-4" /> },
  { id: 'saved', label: 'Saved', icon: <BarChart3 className="w-4 h-4" /> },
  { id: 'history', label: 'History', icon: <History className="w-4 h-4" /> },
  { id: 'plan', label: 'Plan', icon: <GitBranch className="w-4 h-4" /> },
];

export default function TabsPanel() {
  const activeTab = useQueryStore((state) => state.activeTab);
  const setActiveTab = useQueryStore((state) => state.setActiveTab);
  const resultViewMode = useQueryStore((state) => state.resultViewMode);
  const setResultViewMode = useQueryStore((state) => state.setResultViewMode);
  const queryResult = useQueryStore((state) => state.queryResult);
  const savedQueries = useQueryStore((state) => state.savedQueries);
  const queryHistory = useQueryStore((state) => state.queryHistory);
  const loadQuery = useQueryStore((state) => state.loadQuery);
  const replayHistory = useQueryStore((state) => state.replayHistory);
  const loadSavedQueries = useQueryStore((state) => state.loadSavedQueries);
  const loadQueryHistory = useQueryStore((state) => state.loadQueryHistory);
  const isLoadingSaved = useQueryStore((state) => state.isLoadingSaved);
  const isLoadingHistory = useQueryStore((state) => state.isLoadingHistory);
  const currentSavedId = useQueryStore((state) => state.currentSavedId);

  const [showChartConfig, setShowChartConfig] = useState(false);

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const handleTabClick = (tab: TabType) => {
    setActiveTab(tab);
    if (tab === 'saved') {
      loadSavedQueries();
    } else if (tab === 'history') {
      loadQueryHistory();
    }
  };

  return (
    <>
      <div className="border-t border-dark-700 flex-1 flex flex-col min-h-0">
        <div className="flex items-center gap-1 px-2 border-b border-dark-700 flex-shrink-0">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => handleTabClick(tab.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-primary-500 text-primary-400'
                  : 'border-transparent text-dark-400 hover:text-dark-200 hover:border-dark-500'
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-hidden min-h-0">
          {activeTab === 'result' && (
            <div className="h-full flex flex-col">
              {queryResult && (
                <div className="flex items-center gap-2 px-4 py-2 border-b border-dark-700 flex-shrink-0">
                  <button
                    onClick={() => setResultViewMode('table')}
                    className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors ${
                      resultViewMode === 'table'
                        ? 'bg-primary-600 text-white'
                        : 'bg-dark-700 text-dark-300 hover:bg-dark-600'
                    }`}
                  >
                    <Table className="w-3.5 h-3.5" />
                    Table
                  </button>
                  <button
                    onClick={() => setResultViewMode('chart')}
                    className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors ${
                      resultViewMode === 'chart'
                        ? 'bg-primary-600 text-white'
                        : 'bg-dark-700 text-dark-300 hover:bg-dark-600'
                    }`}
                  >
                    <BarChart3 className="w-3.5 h-3.5" />
                    Chart
                  </button>
                </div>
              )}
              <div className="flex-1 min-h-0 overflow-hidden">
                {resultViewMode === 'table' ? (
                  <ResultPanel />
                ) : queryResult ? (
                  <div className="h-full p-4">
                    <ChartView
                      result={queryResult}
                      onConfigClick={() => setShowChartConfig(true)}
                    />
                  </div>
                ) : (
                  <div className="h-full flex items-center justify-center text-dark-400 text-sm">
                    Execute a query to see chart visualization
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'saved' && (
            <div className="h-full overflow-y-auto">
              {isLoadingSaved ? (
                <div className="p-8 text-center text-dark-400">Loading...</div>
              ) : savedQueries.length === 0 ? (
                <div className="p-8 text-center text-dark-400">
                  <BarChart3 className="w-12 h-12 mx-auto mb-2 opacity-50" />
                  <p>No saved queries yet</p>
                  <p className="text-xs mt-1">Click "Save" to save your current query</p>
                </div>
              ) : (
                <div className="divide-y divide-dark-700">
                  {savedQueries.map((query) => (
                    <div
                      key={query.id}
                      className={`p-3 hover:bg-dark-700/50 transition-colors ${
                        query.id === currentSavedId ? 'bg-primary-900/20' : ''
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <h3 className="font-medium text-dark-100 text-sm truncate">
                            {query.name}
                          </h3>
                          {query.description && (
                            <p className="text-xs text-dark-400 mt-1 line-clamp-1">
                              {query.description}
                            </p>
                          )}
                          <p className="text-xs text-dark-500 mt-1">
                            Updated: {formatDate(query.updated_at)}
                          </p>
                        </div>
                        <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                          <button
                            onClick={() => exportQuery(query.id)}
                            className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-600"
                            title="Export SQL"
                          >
                            <Download className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => loadQuery(query)}
                            className="px-2.5 py-1 text-xs bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors flex items-center gap-1"
                          >
                            <Play className="w-3 h-3" />
                            Load
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === 'history' && (
            <div className="h-full overflow-y-auto">
              {isLoadingHistory ? (
                <div className="p-8 text-center text-dark-400">Loading...</div>
              ) : queryHistory.length === 0 ? (
                <div className="p-8 text-center text-dark-400">
                  <History className="w-12 h-12 mx-auto mb-2 opacity-50" />
                  <p>No query history yet</p>
                  <p className="text-xs mt-1">Your executed queries will appear here</p>
                </div>
              ) : (
                <div className="divide-y divide-dark-700">
                  {queryHistory.map((item) => (
                    <div
                      key={item.id}
                      className="p-3 hover:bg-dark-700/50 transition-colors cursor-pointer"
                      onClick={() => replayHistory(item)}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-xs bg-dark-700 text-dark-300 px-1.5 py-0.5 rounded">
                              {item.row_count} rows
                            </span>
                            <span className="text-xs text-dark-500">
                              {item.duration.toFixed(0)}ms
                            </span>
                          </div>
                          <p className="text-xs text-dark-400 mt-1.5 font-mono truncate">
                            {item.sql.substring(0, 80)}...
                          </p>
                          <p className="text-xs text-dark-500 mt-1">
                            {formatDate(item.created_at)}
                          </p>
                        </div>
                        <button
                          className="p-1.5 text-dark-400 hover:text-primary-400 transition-colors rounded hover:bg-dark-600"
                          title="Replay query"
                        >
                          <Play className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === 'plan' && (
            <div className="h-full">
              <ExplainPlan />
            </div>
          )}
        </div>
      </div>

      {showChartConfig && (
        <ChartConfig onClose={() => setShowChartConfig(false)} />
      )}
    </>
  );
}
