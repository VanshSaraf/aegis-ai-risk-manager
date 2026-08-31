"use client";

import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { Boxes, Focus, Network } from "lucide-react";

import type { TransactionGraph } from "@/lib/api";

const nodeColors: Record<string, string> = {
  TRANSACTION: "#5eead4",
  CUSTOMER: "#60a5fa",
  DEVICE: "#a78bfa",
  PAYMENT_INSTRUMENT: "#f59e0b",
  IP_ADDRESS: "#fb7185",
  ADDRESS: "#34d399",
};

function positions(graph: TransactionGraph): Node[] {
  const current = graph.nodes.filter((node) => node.is_current);
  const historical = graph.nodes.filter((node) => !node.is_current);
  const makeNode = (node: TransactionGraph["nodes"][number], x: number, y: number): Node => ({
    id: node.id,
    position: { x, y },
    data: { label: node.label, metadata: node },
    style: {
      width: node.type === "TRANSACTION" ? 150 : 132,
      border: `1px solid ${nodeColors[node.type] ?? "#64748b"}`,
      background: node.is_current ? "#141c27" : "#0d121a",
      color: "#e5edf7",
      borderRadius: 10,
      fontSize: 11,
      fontFamily: "var(--font-geist-mono)",
      padding: "10px 12px",
      boxShadow: node.is_current ? `0 0 0 2px ${nodeColors[node.type] ?? "#64748b"}22` : "none",
    },
  });
  const currentNodes = current.map((node) => {
    if (node.type === "TRANSACTION") return makeNode(node, 330, 10);
    const entityIndex = current.filter((item) => item.type !== "TRANSACTION").indexOf(node);
    return makeNode(node, 35 + entityIndex * 145, 135);
  });
  const historicalNodes = historical.map((node, index) =>
    makeNode(node, 25 + (index % 5) * 148, 285 + Math.floor(index / 5) * 100),
  );
  return [...currentNodes, ...historicalNodes];
}

export function GraphPanel({
  graph,
  loading,
  error,
  onRetry,
}: {
  graph: TransactionGraph | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const nodes = useMemo(() => (graph ? positions(graph) : []), [graph]);
  const edges = useMemo<Edge[]>(
    () =>
      graph?.edges.map((edge) => ({
        ...edge,
        label: edge.type === "INVOLVES" ? undefined : edge.type.replaceAll("_", " ").toLowerCase(),
        markerEnd: { type: MarkerType.ArrowClosed, color: "#40516a" },
        animated: edge.type !== "INVOLVES",
        style: { stroke: "#40516a", strokeWidth: edge.type === "INVOLVES" ? 1.5 : 1 },
        labelStyle: { fill: "#75849a", fontSize: 8 },
      })) ?? [],
    [graph],
  );
  const selectedNode = graph?.nodes.find((node) => node.id === selectedNodeId) ?? null;

  return (
    <section className="panel graph-panel" aria-labelledby="graph-title">
      <div className="panel-heading">
        <div>
          <div className="eyebrow"><Network size={13} /> Identity graph</div>
          <h2 id="graph-title">Point-in-time relationships</h2>
        </div>
        {graph?.cluster_id && <span className="cluster-badge">{graph.cluster_id}</span>}
      </div>

      {loading ? (
        <div className="graph-skeleton skeleton" />
      ) : error ? (
        <div className="panel-state">
          <Boxes size={24} />
          <strong>Graph unavailable</strong>
          <span>{error}</span>
          <button onClick={onRetry}>Retry graph</button>
        </div>
      ) : !graph ? (
        <div className="panel-state"><Focus size={24} /><span>Select an assessed transaction to inspect its graph.</span></div>
      ) : (
        <>
          <div className="graph-canvas">
            <ReactFlow
              key={graph.transaction_id}
              nodes={nodes}
              edges={edges}
              fitView
              fitViewOptions={{ padding: 0.18 }}
              minZoom={0.25}
              maxZoom={1.6}
              nodesDraggable
              nodesConnectable={false}
              elementsSelectable
              onNodeClick={(_, node) => setSelectedNodeId(node.id)}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#1f2a38" gap={22} size={1} />
              <Controls showInteractive={false} position="bottom-right" />
            </ReactFlow>
          </div>
          <div className="graph-footer">
            <div className="graph-legend">
              {Object.entries(nodeColors).slice(1).map(([type, color]) => (
                <span key={type}><i style={{ background: color }} />{type.replace("PAYMENT_INSTRUMENT", "INSTRUMENT").replace("IP_ADDRESS", "IP")}</span>
              ))}
            </div>
            <span>{graph.nodes.length}/{graph.max_nodes} nodes · {graph.edges.length}/{graph.max_edges} edges</span>
          </div>
          {!graph.has_prior_relationships && (
            <div className="graph-empty">No prior identity relationships were available at this transaction&apos;s scoring time.</div>
          )}
          {selectedNode && (
            <div className="node-detail">
              <span>{selectedNode.type.replaceAll("_", " ")}</span>
              <code>{selectedNode.id}</code>
              <strong>{selectedNode.connection_count} visible connections</strong>
              <button aria-label="Close node details" onClick={() => setSelectedNodeId(null)}>×</button>
            </div>
          )}
          {graph.signals.length > 0 && (
            <div className="signal-strip">
              {graph.signals.map((signal) => <span key={signal.code}>{signal.label}</span>)}
            </div>
          )}
        </>
      )}
    </section>
  );
}
