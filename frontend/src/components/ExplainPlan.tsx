import { useState, useCallback, useMemo } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  Handle,
  Position,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { AlertTriangle, Database, Table } from 'lucide-react';
import { useQueryStore } from '@/store/queryStore';
import type { ExplainPlanNode, ExplainPlanEdge } from '@/types';

const nodeWidth = 200;
const nodeHeight = 80;
const levelGap = 120;
const nodeGap = 20;

function PlanNode({ data }: { data: any }) {
  const node = data.node as ExplainPlanNode;

  return (
    <div
      className={`px-3 py-2 rounded-lg border-2 shadow-lg ${
        node.isFullScan
          ? 'bg-red-900/80 border-red-500'
          : 'bg-dark-800 border-dark-600'
      }`}
      style={{ width: nodeWidth, minHeight: nodeHeight }}
    >
      <Handle type="target" position={Position.Top} className="!bg-primary-500" />
      
      <div className="flex items-start gap-2">
        {node.isFullScan ? (
          <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
        ) : (
          <Database className="w-5 h-5 text-primary-400 flex-shrink-0 mt-0.5" />
        )}
        <div className="flex-1 min-w-0">
          <div className="font-medium text-dark-100 text-sm truncate">
            {node.tableName || 'Query'}
          </div>
          {node.indexName && (
            <div className="text-xs text-emerald-400 mt-0.5">
              Index: {node.indexName}
            </div>
          )}
          {node.isFullScan && (
            <div className="text-xs text-red-400 mt-0.5 font-medium">
              ⚠ FULL TABLE SCAN
            </div>
          )}
          {node.estimatedRows && (
            <div className="text-xs text-dark-400 mt-0.5">
              ~{node.estimatedRows.toLocaleString()} rows
            </div>
          )}
        </div>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-primary-500" />
    </div>
  );
}

const nodeTypes = {
  plan: PlanNode,
};

function layoutNodes(nodes: ExplainPlanNode[], edges: ExplainPlanEdge[]): { nodes: Node[]; edges: Edge[] } {
  const nodeMap = new Map<string, ExplainPlanNode>();
  nodes.forEach(n => nodeMap.set(n.id, n));

  const childrenMap = new Map<string, string[]>();
  nodes.forEach(n => childrenMap.set(n.id, []));
  edges.forEach(e => {
    childrenMap.get(e.source)?.push(e.target);
  });

  const levelMap = new Map<string, number>();
  const roots = nodes.filter(n => !n.parentId);
  
  function assignLevel(nodeId: string, level: number) {
    levelMap.set(nodeId, level);
    const children = childrenMap.get(nodeId) || [];
    children.forEach(childId => assignLevel(childId, level + 1));
  }
  roots.forEach(root => assignLevel(root.id, 0));

  const maxLevel = Math.max(...levelMap.values(), 0);
  const levelNodes = new Map<number, string[]>();
  for (let i = 0; i <= maxLevel; i++) {
    levelNodes.set(i, []);
  }
  levelMap.forEach((level, nodeId) => {
    levelNodes.get(level)?.push(nodeId);
  });

  const flowNodes: Node[] = [];
  nodes.forEach(node => {
    const level = levelMap.get(node.id) || 0;
    const levelNodeIds = levelNodes.get(level) || [];
    const posInLevel = levelNodeIds.indexOf(node.id);
    const levelWidth = levelNodeIds.length * (nodeWidth + nodeGap) - nodeGap;
    const startX = -levelWidth / 2;
    
    flowNodes.push({
      id: node.id,
      type: 'plan',
      position: {
        x: startX + posInLevel * (nodeWidth + nodeGap),
        y: level * (nodeHeight + levelGap),
      },
      data: { node },
    });
  });

  const flowEdges: Edge[] = edges.map(edge => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: 'smoothstep',
    animated: true,
    style: { stroke: '#475569', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#475569' },
  }));

  return { nodes: flowNodes, edges: flowEdges };
}

export default function ExplainPlan() {
  const explainResult = useQueryStore((state) => state.explainResult);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const { nodes: flowNodes, edges: flowEdges } = useMemo(() => {
    if (!explainResult) return { nodes: [], edges: [] };
    return layoutNodes(explainResult.queryPlan.nodes, explainResult.queryPlan.edges);
  }, [explainResult]);

  const handleNodeMouseEnter = useCallback((_: React.MouseEvent, node: Node) => {
    setHoveredNode(node.id);
  }, []);

  const handleNodeMouseLeave = useCallback(() => {
    setHoveredNode(null);
  }, []);

  const hoveredPlanNode = hoveredNode && explainResult?.queryPlan.nodes.find(n => n.id === hoveredNode);

  if (!explainResult) {
    return (
      <div className="h-full flex items-center justify-center text-dark-400 text-sm">
        <div className="text-center">
          <Table className="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p>Click "Explain" to see the query execution plan</p>
        </div>
      </div>
    );
  }

  const fullScanCount = explainResult.queryPlan.nodes.filter(n => n.isFullScan).length;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between p-3 border-b border-dark-700">
        <div className="flex items-center gap-4">
          <span className="text-sm text-dark-300">
            {explainResult.queryPlan.nodes.length} operations
          </span>
          {fullScanCount > 0 && (
            <span className="text-xs bg-red-900/50 text-red-300 px-2 py-0.5 rounded flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              {fullScanCount} full table scan{fullScanCount > 1 ? 's' : ''}
            </span>
          )}
        </div>
        {hoveredPlanNode && (
          <div className="text-xs text-dark-400 font-mono truncate max-w-md">
            {hoveredPlanNode.detail}
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          onNodeMouseEnter={handleNodeMouseEnter}
          onNodeMouseLeave={handleNodeMouseLeave}
          fitView
          fitViewOptions={{ padding: 0.5 }}
          className="bg-dark-900"
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#334155" gap={20} />
          <Controls
            className="!bg-dark-800 !border-dark-600"
            position="bottom-right"
          />
          <MiniMap
            nodeColor={(n) => (n.data.node.isFullScan ? '#ef4444' : '#3b82f6')}
            nodeStrokeWidth={2}
            className="!bg-dark-800 !border-dark-600"
            position="bottom-left"
          />
        </ReactFlow>
      </div>

      <div className="p-3 border-t border-dark-700 bg-dark-800/50">
        <div className="text-xs font-mono text-dark-400 overflow-x-auto whitespace-pre-wrap max-h-24 overflow-y-auto">
          {explainResult.sql}
        </div>
      </div>
    </div>
  );
}
