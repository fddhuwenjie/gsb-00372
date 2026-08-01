import { useCallback, useRef, useEffect } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type NodeTypes,
  BackgroundVariant,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useQueryStore } from '@/store/queryStore';
import TableNode from './TableNode';
import type { TableNode as TableNodeType, Join } from '@/types';

const nodeTypes: NodeTypes = {
  table: TableNode,
};

interface QueryCanvasProps {
  onDrop: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
}

let nodeId = 0;
let aliasCounter: Record<string, number> = {};

function getAlias(tableName: string): string {
  if (!aliasCounter[tableName]) {
    aliasCounter[tableName] = 0;
  }
  aliasCounter[tableName]++;
  const count = aliasCounter[tableName];
  const base = tableName.substring(0, 2).toLowerCase();
  return count > 1 ? `${base}${count}` : base;
}

export default function QueryCanvas({ onDrop, onDragOver }: QueryCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const addTable = useQueryStore((state) => state.addTable);
  const updateTablePosition = useQueryStore((state) => state.updateTablePosition);
  const addJoin = useQueryStore((state) => state.addJoin);
  const tables = useQueryStore((state) => state.tables);
  const joins = useQueryStore((state) => state.joins);
  const suggestedJoins = useQueryStore((state) => state.suggestedJoins);

  useEffect(() => {
    const newNodes: Node[] = tables.map((table) => ({
      id: table.id,
      type: 'table',
      position: table.position,
      data: {
        tableName: table.tableName,
        alias: table.alias,
      },
    }));
    setNodes(newNodes);
  }, [tables, setNodes]);

  useEffect(() => {
    const allJoins = [...joins, ...suggestedJoins];
    const newEdges: Edge[] = allJoins.map((join) => ({
      id: join.id,
      source: join.leftTableId,
      target: join.rightTableId,
      label: join.type,
      data: { join },
      animated: suggestedJoins.some((j) => j.id === join.id),
      style: {
        stroke: suggestedJoins.some((j) => j.id === join.id) ? '#f59e0b' : '#0ea5e9',
        strokeWidth: 2,
      },
      labelStyle: {
        fill: suggestedJoins.some((j) => j.id === join.id) ? '#f59e0b' : '#0ea5e9',
        fontSize: 11,
        fontWeight: 600,
      },
      labelBgStyle: {
        fill: '#1e293b',
        fillOpacity: 0.9,
      },
    }));
    setEdges(newEdges);
  }, [joins, suggestedJoins, setEdges]);

  const handleNodeDragStop = useCallback(
    (_: React.MouseEvent, node: Node) => {
      updateTablePosition(node.id, node.position);
    },
    [updateTablePosition]
  );

  const handleConnect = useCallback(
    (params: Connection) => {
      const sourceTable = tables.find((t) => t.id === params.source);
      const targetTable = tables.find((t) => t.id === params.target);
      
      if (!sourceTable || !targetTable) return;

      const metadata = useQueryStore.getState().metadata;
      const sourceMeta = metadata.find((m) => m.name === sourceTable.tableName);
      const targetMeta = metadata.find((m) => m.name === targetTable.tableName);
      
      if (!sourceMeta || !targetMeta) return;

      let leftColumn = '';
      let rightColumn = '';

      for (const fk of sourceMeta.foreignKeys) {
        if (fk.toTable === targetTable.tableName) {
          leftColumn = fk.fromColumn;
          rightColumn = fk.toColumn;
          break;
        }
      }

      if (!leftColumn) {
        for (const fk of targetMeta.foreignKeys) {
          if (fk.toTable === sourceTable.tableName) {
            leftColumn = fk.toColumn;
            rightColumn = fk.fromColumn;
            break;
          }
        }
      }

      if (!leftColumn || !rightColumn) {
        const sourcePk = sourceMeta.columns.find((c) => c.isPrimaryKey);
        const targetPk = targetMeta.columns.find((c) => c.isPrimaryKey);
        if (sourcePk && targetPk) {
          leftColumn = sourcePk.name;
          rightColumn = targetPk.name;
        } else {
          return;
        }
      }

      const newJoin: Join = {
        id: `edge-${Date.now()}`,
        type: 'INNER',
        leftTableId: sourceTable.id,
        leftColumn,
        rightTableId: targetTable.id,
        rightColumn,
        leftTable: sourceTable.tableName,
        rightTable: targetTable.tableName,
      };

      addJoin(newJoin);
      setEdges((eds) => addEdge({ ...params, label: 'INNER' }, eds));
    },
    [tables, addJoin, setEdges]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const tableName = e.dataTransfer.getData('tableName');
      if (!tableName) return;

      const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!reactFlowBounds) return;

      const position = {
        x: e.clientX - reactFlowBounds.left - 120,
        y: e.clientY - reactFlowBounds.top - 50,
      };

      nodeId++;
      const newTable: TableNodeType = {
        id: `node-${nodeId}`,
        tableName,
        alias: getAlias(tableName),
        position,
      };

      addTable(newTable);

      const newNode: Node = {
        id: newTable.id,
        type: 'table',
        position,
        data: {
          tableName: newTable.tableName,
          alias: newTable.alias,
        },
      };

      setNodes((nds) => [...nds, newNode]);
      onDrop(e);
    },
    [addTable, setNodes, onDrop]
  );

  const handleEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      const join = edge.data?.join as Join;
      if (!join) return;

      const isSuggested = suggestedJoins.some((j) => j.id === join.id);
      if (isSuggested) {
        addJoin({
          ...join,
          id: `edge-${Date.now()}`,
        });
      }
    },
    [suggestedJoins, addJoin]
  );

  return (
    <div ref={reactFlowWrapper} className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
        onNodeDragStop={handleNodeDragStop}
        onDrop={handleDrop}
        onDragOver={onDragOver}
        onEdgeClick={handleEdgeClick}
        nodeTypes={nodeTypes}
        fitView
        snapToGrid
        snapGrid={[15, 15]}
        className="bg-dark-900"
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#334155" />
        <Controls className="bg-dark-800 border-dark-600 text-dark-100" />
        <MiniMap
          className="bg-dark-800 border-dark-600"
          nodeColor="#0ea5e9"
          maskColor="rgba(15, 23, 42, 0.7)"
        />
      </ReactFlow>
    </div>
  );
}
