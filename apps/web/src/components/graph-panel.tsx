"use client";

import { useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  Panel,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { Boxes, Focus, Maximize2, Network, X } from "lucide-react";

import type { TransactionGraph } from "@/lib/api";
import { humanizeNodeType, humanizeSignal, technicalSignalCode } from "@/lib/presentation";

const nodeColors: Record<string, string> = {
  TRANSACTION: "#5eead4",
  CUSTOMER: "#60a5fa",
  DEVICE: "#a78bfa",
  PAYMENT_INSTRUMENT: "#f59e0b",
  IP_ADDRESS: "#fb7185",
  ADDRESS: "#34d399",
};

function signalContext(graph: TransactionGraph, code: string): string {
  const currentDevice = graph.nodes.find((node) => node.type === "DEVICE" && node.is_current);
  const connectedCount = (type: string) => {
    if (!currentDevice) return 0;
    const ids = new Set(
      graph.edges.flatMap((edge) => {
        if (edge.source === currentDevice.id) return [edge.target];
        if (edge.target === currentDevice.id) return [edge.source];
        return [];
      }),
    );
    return graph.nodes.filter((node) => ids.has(node.id) && node.type === type).length;
  };
  if (code === "DEVICE_MULTI_CUSTOMER_CONCENTRATION") {
    return `${connectedCount("CUSTOMER")} customer nodes connect to the current device in this visible neighborhood.`;
  }
  if (code === "DEVICE_MULTI_INSTRUMENT_CONCENTRATION") {
    return `${connectedCount("PAYMENT_INSTRUMENT")} instrument nodes connect to the current device in this visible neighborhood.`;
  }
  if (code === "RAPID_RELATIONSHIP_EXPANSION") {
    return "The point-in-time identity neighborhood expanded unusually quickly relative to prior activity.";
  }
  if (code === "MULTI_COMPONENT_BRIDGE") {
    return "This payment connects identity structures that were historically separate.";
  }
  if (code === "DENSE_MULTI_ENTITY_STRUCTURE") {
    return "Multiple entity types form dense, overlapping infrastructure in the historical graph.";
  }
  return "A named structural signal was present in the immutable graph assessment.";
}

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
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const fitViewRef = useRef<(() => Promise<boolean>) | null>(null);
  const focusedNodeId = selectedNodeId ?? hoveredNodeId;
  const connectedNodeIds = useMemo(() => {
    if (!graph || !focusedNodeId) return new Set<string>();
    const ids = new Set<string>([focusedNodeId]);
    graph.edges.forEach((edge) => {
      if (edge.source === focusedNodeId) ids.add(edge.target);
      if (edge.target === focusedNodeId) ids.add(edge.source);
    });
    return ids;
  }, [focusedNodeId, graph]);
  const nodes = useMemo(
    () =>
      graph
        ? positions(graph).map((node) => ({
            ...node,
            style: {
              ...node.style,
              opacity: focusedNodeId && !connectedNodeIds.has(node.id) ? 0.18 : 1,
              boxShadow:
                node.id === focusedNodeId
                  ? `0 0 0 3px ${nodeColors[String(node.data.metadata && (node.data.metadata as TransactionGraph["nodes"][number]).type)] ?? "#72ded0"}30, 0 12px 30px rgba(0,0,0,.35)`
                  : node.style?.boxShadow,
              transition: "opacity 160ms ease, box-shadow 160ms ease",
            },
            zIndex: node.id === focusedNodeId ? 3 : connectedNodeIds.has(node.id) ? 2 : 1,
          }))
        : [],
    [connectedNodeIds, focusedNodeId, graph],
  );
  const edges = useMemo<Edge[]>(
    () =>
      graph?.edges.map((edge) => ({
        ...edge,
        type: "default",
        label: edge.type === "INVOLVES" ? undefined : edge.type.replaceAll("_", " ").toLowerCase(),
        markerEnd: { type: MarkerType.ArrowClosed, color: "#40516a" },
        animated:
          edge.type !== "INVOLVES" &&
          (!focusedNodeId || edge.source === focusedNodeId || edge.target === focusedNodeId),
        style: {
          stroke:
            focusedNodeId && (edge.source === focusedNodeId || edge.target === focusedNodeId)
              ? "#9d8cff"
              : "#40516a",
          strokeWidth:
            focusedNodeId && (edge.source === focusedNodeId || edge.target === focusedNodeId)
              ? 2
              : edge.type === "INVOLVES"
                ? 1.5
                : 1,
          opacity:
            focusedNodeId && edge.source !== focusedNodeId && edge.target !== focusedNodeId
              ? 0.12
              : 1,
          transition: "opacity 160ms ease, stroke 160ms ease",
        },
        labelStyle: { fill: "#8c9aad", fontSize: 8 },
        labelBgStyle: { fill: "#0b1119", fillOpacity: 0.94 },
        labelBgPadding: [4, 2],
        labelBgBorderRadius: 3,
      })) ?? [],
    [focusedNodeId, graph],
  );
  const selectedNode = graph?.nodes.find((node) => node.id === focusedNodeId) ?? null;

  const resetView = () => {
    setSelectedNodeId(null);
    setHoveredNodeId(null);
    void fitViewRef.current?.();
  };

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
              zoomOnScroll={false}
              nodesDraggable
              nodesConnectable={false}
              elementsSelectable
              onInit={(instance) => {
                fitViewRef.current = () => instance.fitView({ padding: 0.18, duration: 260 });
              }}
              onNodeClick={(_, node) => setSelectedNodeId(node.id)}
              onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
              onNodeMouseLeave={() => setHoveredNodeId(null)}
              onPaneClick={() => setSelectedNodeId(null)}
            >
              <Background color="#1f2a38" gap={22} size={1} />
              <Controls showInteractive={false} position="bottom-right" />
              <Panel position="top-right">
                <button className="graph-reset" onClick={resetView} type="button">
                  <Maximize2 size={13} /> Reset view
                </button>
              </Panel>
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
              <span>{humanizeNodeType(selectedNode.type)}</span>
              <code>{selectedNode.id}</code>
              <strong>{selectedNode.connection_count} visible connections</strong>
              <small>Direct neighbors are highlighted in the graph.</small>
              {selectedNodeId && <button aria-label="Close node details" onClick={() => setSelectedNodeId(null)}><X size={13} /></button>}
            </div>
          )}
          {graph.signals.length > 0 && (
            <div className="signal-strip">
              {graph.signals.map((signal) => (
                <article key={signal.code}>
                  <strong>{humanizeSignal(signal.code, signal.label)}</strong>
                  <p>{signalContext(graph, signal.code)}</p>
                  <code>{technicalSignalCode(signal.code)}</code>
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
