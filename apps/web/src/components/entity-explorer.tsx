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
import {
  ArrowLeft,
  ArrowRight,
  Clock3,
  Focus,
  GitBranch,
  Maximize2,
  Network,
  SearchX,
  ShieldAlert,
  X,
} from "lucide-react";

import { ActionBadge } from "@/components/action-badge";
import { RelationshipPathCard } from "@/components/relationship-path-card";
import type {
  DashboardTransaction,
  EntityIntelligence,
  EntityType,
} from "@/lib/api";
import { humanizeSignal, technicalSignalCode } from "@/lib/presentation";
import { findRelationshipPath } from "@/lib/relationship-path";

const nodeColors: Record<EntityType, string> = {
  CUSTOMER: "#60a5fa",
  DEVICE: "#a78bfa",
  PAYMENT_INSTRUMENT: "#f59e0b",
  IP_ADDRESS: "#fb7185",
  ADDRESS: "#34d399",
};

export interface EntityReference {
  entityType: EntityType;
  publicId: string;
}

function formatTime(value: string | null): string {
  if (!value) return "Not observed";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatAmount(amountPaise: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amountPaise / 100);
}

function shortId(value: string): string {
  return `${value.slice(0, 7)}…${value.slice(-5)}`;
}

function entityLabel(type: EntityType): string {
  return type
    .replace("PAYMENT_INSTRUMENT", "INSTRUMENT")
    .replace("IP_ADDRESS", "IP")
    .replaceAll("_", " ");
}

function networkPositions(data: EntityIntelligence): Node[] {
  const center = data.network.nodes.find((node) => node.is_center);
  const neighbors = data.network.nodes.filter((node) => !node.is_center);
  const centerNode: Node[] = center
    ? [
        {
          id: center.id,
          position: { x: 410, y: 245 },
          data: { label: center.label, metadata: center },
          style: {
            width: 164,
            border: `1px solid ${nodeColors[center.type]}`,
            background: "#17212d",
            color: "#f0f5fa",
            borderRadius: 12,
            fontSize: 11,
            fontFamily: "var(--font-geist-mono)",
            padding: "12px 14px",
            boxShadow: `0 0 0 3px ${nodeColors[center.type]}28, 0 18px 50px rgba(0,0,0,.4)`,
          },
        },
      ]
    : [];
  return [
    ...centerNode,
    ...neighbors.map((node, index): Node => {
      const angle = (index / Math.max(1, neighbors.length)) * Math.PI * 2 - Math.PI / 2;
      const ring = index % 2 === 0 ? 235 : 310;
      return {
        id: node.id,
        position: {
          x: 425 + Math.cos(angle) * ring,
          y: 250 + Math.sin(angle) * ring * 0.72,
        },
        data: { label: node.label, metadata: node },
        style: {
          width: 138,
          border: `1px solid ${nodeColors[node.type]}`,
          background: "#0d141d",
          color: "#dce5ee",
          borderRadius: 9,
          fontSize: 10,
          fontFamily: "var(--font-geist-mono)",
          padding: "9px 11px",
        },
      };
    }),
  ];
}

function EntityNetworkGraph({
  data,
  onPivot,
}: {
  data: EntityIntelligence;
  onPivot: (reference: EntityReference) => void;
}) {
  const [selectedId, setSelectedId] = useState(data.entity.public_id);
  const [pathStartId, setPathStartId] = useState<string | null>(null);
  const fitViewRef = useRef<(() => Promise<boolean>) | null>(null);
  const activePath = useMemo(
    () =>
      pathStartId
        ? findRelationshipPath(
            data.network.nodes,
            data.network.edges,
            pathStartId,
            data.entity.public_id,
          )
        : null,
    [data, pathStartId],
  );
  const pathNodeIds = useMemo(() => {
    const ids = new Set(activePath?.nodes.map((node) => node.id) ?? []);
    if (pathStartId) {
      ids.add(pathStartId);
      ids.add(data.entity.public_id);
    }
    return ids;
  }, [activePath, data.entity.public_id, pathStartId]);
  const pathEdgeIds = useMemo(
    () => new Set(activePath?.edges.map((edge) => edge.id) ?? []),
    [activePath],
  );
  const connectedIds = useMemo(() => {
    const values = new Set([selectedId]);
    data.network.edges.forEach((edge) => {
      if (edge.source === selectedId) values.add(edge.target);
      if (edge.target === selectedId) values.add(edge.source);
    });
    return values;
  }, [data.network.edges, selectedId]);
  const nodes = useMemo(
    () =>
      networkPositions(data).map((node) => ({
        ...node,
        style: {
          ...node.style,
          opacity: pathStartId
            ? pathNodeIds.has(node.id)
              ? 1
              : 0.1
            : connectedIds.has(node.id)
              ? 1
              : 0.2,
          boxShadow:
            pathNodeIds.has(node.id)
              ? `0 0 0 3px ${nodeColors[(node.data.metadata as EntityIntelligence["network"]["nodes"][number]).type]}48, 0 18px 45px rgba(0,0,0,.42)`
              : node.id === selectedId
              ? `0 0 0 3px ${nodeColors[(node.data.metadata as EntityIntelligence["network"]["nodes"][number]).type]}35, 0 16px 40px rgba(0,0,0,.38)`
              : node.style?.boxShadow,
          transition: "opacity 150ms ease, box-shadow 150ms ease",
        },
      })),
    [connectedIds, data, pathNodeIds, pathStartId, selectedId],
  );
  const edges = useMemo<Edge[]>(
    () =>
      data.network.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.type.replaceAll("_", " ").toLowerCase(),
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: pathEdgeIds.has(edge.id) ? "#5eead4" : "#42536a",
        },
        style: {
          stroke:
            pathEdgeIds.has(edge.id)
              ? "#5eead4"
              : edge.source === selectedId || edge.target === selectedId
                ? "#9d8cff"
                : "#42536a",
          strokeWidth: pathEdgeIds.has(edge.id)
            ? 3
            : edge.source === selectedId || edge.target === selectedId
              ? 1.8
              : 1,
          opacity:
            pathStartId
              ? pathEdgeIds.has(edge.id)
                ? 1
                : 0.07
              : edge.source === selectedId || edge.target === selectedId
                ? 1
                : 0.14,
          transition: "opacity 150ms ease, stroke 150ms ease",
        },
        labelStyle: {
          fill: pathEdgeIds.has(edge.id) ? "#a8eee5" : "#8290a2",
          fontSize: 8,
          opacity: pathStartId ? (pathEdgeIds.has(edge.id) ? 1 : 0.1) : 1,
        },
        labelBgStyle: { fill: "#0a1017", fillOpacity: 0.95 },
        labelBgPadding: [4, 2],
        labelBgBorderRadius: 3,
      })),
    [data.network.edges, pathEdgeIds, pathStartId, selectedId],
  );
  const selected = data.network.nodes.find((node) => node.id === selectedId) ?? null;

  return (
    <>
      <div className="entity-network-canvas">
        <ReactFlow
        key={data.entity.public_id}
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.16 }}
        minZoom={0.3}
        maxZoom={1.7}
        zoomOnScroll={false}
        nodesDraggable
        nodesConnectable={false}
        onInit={(instance) => {
          fitViewRef.current = () => instance.fitView({ padding: 0.16, duration: 220 });
        }}
        onNodeClick={(_, node) => setSelectedId(node.id)}
      >
        <Background color="#202c3b" gap={22} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
        <Panel position="top-right">
          <button
            className="graph-reset"
            onClick={() => {
              setSelectedId(data.entity.public_id);
              setPathStartId(null);
              void fitViewRef.current?.();
            }}
            type="button"
          >
            <Maximize2 size={13} /> Reset view
          </button>
        </Panel>
        </ReactFlow>
        {selected && (
          <div className="entity-node-detail">
            <span>{entityLabel(selected.type)}</span>
            <code>{selected.id}</code>
            <strong>{selected.connection_count} visible connections</strong>
            {!selected.is_center && (
              <>
                <button onClick={() => setPathStartId(selected.id)} type="button">
                  <GitBranch size={13} /> Explain connection
                </button>
                <button
                  onClick={() =>
                    onPivot({ entityType: selected.type, publicId: selected.id })
                  }
                  type="button"
                >
                  Pivot to entity <ArrowRight size={13} />
                </button>
              </>
            )}
          </div>
        )}
      </div>
      {pathStartId && (
        <RelationshipPathCard
          path={activePath}
          context="CURRENT_OBSERVED_HISTORY"
          onClear={() => setPathStartId(null)}
          onEntityAction={(node) => {
            onPivot({ entityType: node.type as EntityType, publicId: node.id });
          }}
          canEntityAction={(node) => node.id !== data.entity.public_id}
          entityActionLabel="Pivot to entity"
        />
      )}
    </>
  );
}

export function EntityExplorer({
  path,
  data,
  loading,
  error,
  onPivot,
  onBack,
  onBreadcrumb,
  onClose,
  onRetry,
  onInvestigate,
}: {
  path: EntityReference[];
  data: EntityIntelligence | null;
  loading: boolean;
  error: string | null;
  onPivot: (reference: EntityReference) => void;
  onBack: () => void;
  onBreadcrumb: (index: number) => void;
  onClose: () => void;
  onRetry: () => void;
  onInvestigate: (transaction: DashboardTransaction) => void;
}) {
  const active = path.at(-1);
  if (!active) return null;
  const summary = data?.summary;
  const counts = data?.risk_context.recent_action_counts;

  return (
    <section className="entity-explorer" aria-labelledby="entity-explorer-title">
      <header className="entity-explorer-header">
        <div>
          <div className="eyebrow"><Network size={13} /> Entity intelligence</div>
          <h2 id="entity-explorer-title">Current observed network</h2>
          <p>This operational view includes persisted activity up to the current data horizon. Transaction investigations remain strictly point-in-time.</p>
        </div>
        <div className="entity-header-actions">
          <button onClick={onBack} disabled={path.length === 1} type="button"><ArrowLeft size={14} /> Back</button>
          <button onClick={onClose} type="button"><X size={14} /> Return to payment</button>
        </div>
      </header>

      <nav className="entity-breadcrumbs" aria-label="Entity pivot history">
        {path.map((item, index) => (
          <span key={`${item.entityType}-${item.publicId}-${index}`}>
            {index > 0 && <ArrowRight size={11} />}
            <button onClick={() => onBreadcrumb(index)} type="button">
              {entityLabel(item.entityType)} <code>{shortId(item.publicId)}</code>
            </button>
          </span>
        ))}
      </nav>

      {loading ? (
        <div className="entity-loading skeleton" />
      ) : error || !data ? (
        <div className="panel-state entity-state"><ShieldAlert size={26} /><strong>Entity intelligence unavailable</strong><span>{error ?? "No entity data was returned."}</span><button onClick={onRetry}>Retry entity</button></div>
      ) : (
        <>
          <section className="entity-profile" aria-label="Entity profile">
            <div className="entity-profile-id">
              <span>{entityLabel(data.entity.entity_type)}</span>
              <code>{data.entity.public_id}</code>
            </div>
            <div><span>First observed</span><strong>{formatTime(data.entity.first_observed_at)}</strong></div>
            <div><span>Last observed</span><strong>{formatTime(data.entity.last_observed_at)}</strong></div>
            <div><span>Transactions</span><strong>{data.entity.transaction_count.toLocaleString("en-IN")}</strong></div>
            <div><span>Highest recent transaction score</span><strong>{data.risk_context.highest_recent_transaction_score?.toFixed(3) ?? "Not assessed"}</strong><small>Uncalibrated transaction score</small></div>
          </section>

          <section className="entity-summary" aria-label="Visible entity network summary">
            <span>Customers<strong>{summary?.visible_customers ?? 0}</strong></span>
            <span>Devices<strong>{summary?.visible_devices ?? 0}</strong></span>
            <span>Instruments<strong>{summary?.visible_instruments ?? 0}</strong></span>
            <span>IPs<strong>{summary?.visible_ips ?? 0}</strong></span>
            <span>Addresses<strong>{summary?.visible_addresses ?? 0}</strong></span>
            <span>Relationships<strong>{summary?.visible_relationships ?? 0}</strong></span>
          </section>

          <div className="entity-explorer-grid">
            <section className="entity-network-panel" aria-labelledby="entity-network-title">
              <div className="entity-section-heading">
                <div><div className="eyebrow"><GitBranch size={13} /> Network explorer</div><h3 id="entity-network-title">Connected infrastructure</h3></div>
                <span className={data.network.truncated ? "bounded-badge truncated" : "bounded-badge"}>{data.network.nodes.length}/{data.network.max_nodes} nodes · {data.network.edges.length}/{data.network.max_edges} relationships</span>
              </div>
              <EntityNetworkGraph key={data.entity.public_id} data={data} onPivot={onPivot} />
              <div className="entity-network-footer">
                <div>{Object.entries(nodeColors).map(([type, color]) => <span key={type}><i style={{ background: color }} />{entityLabel(type as EntityType)}</span>)}</div>
                <p>{data.network.truncated ? "Bounded view · additional relationships exist outside this visible neighborhood." : "Complete one-hop neighborhood for this entity."}</p>
              </div>
            </section>

            <aside className="entity-intelligence-rail">
              <section className="entity-context-section">
                <h3>Recent action context</h3>
                <p>Policy actions among the {data.recent_transactions.length} recent transactions shown.</p>
                <div className="entity-action-counts">
                  <span>Allow<strong>{counts?.allow ?? 0}</strong></span>
                  <span>Verify<strong>{counts?.verify ?? 0}</strong></span>
                  <span>Hold<strong>{counts?.hold ?? 0}</strong></span>
                  <span>Escalate<strong>{counts?.escalate ?? 0}</strong></span>
                  <span>Recommend block<strong>{counts?.recommend_block ?? 0}</strong></span>
                </div>
              </section>

              <section className="entity-context-section">
                <h3>Signals observed in this network</h3>
                <p>Transaction-level structural signals from recent assessed payments linked to this entity. They are not attributed causally to the entity.</p>
                {data.structural_context.length ? <div className="entity-signals">{data.structural_context.map((signal) => <article key={signal.code}><strong>{humanizeSignal(signal.code, signal.label)}</strong><code>{technicalSignalCode(signal.code)}</code></article>)}</div> : <div className="entity-empty-context"><Focus size={15} /> No named structural signals in recent assessed transactions.</div>}
              </section>

              <section className="entity-context-section entity-connections">
                <h3>Connection reasons</h3>
                {data.network.edges.slice(0, 8).map((edge) => <article key={edge.id}><div><code>{shortId(edge.source)}</code><span>{edge.type.replaceAll("_", " ")}</span><code>{shortId(edge.target)}</code></div><small>{edge.observation_count} observation{edge.observation_count === 1 ? "" : "s"} · last {formatTime(edge.last_seen_at)}</small></article>)}
              </section>
            </aside>
          </div>

          <section className="entity-transactions" aria-labelledby="entity-transactions-title">
            <div className="entity-section-heading">
              <div><div className="eyebrow"><Clock3 size={13} /> Entity activity</div><h3 id="entity-transactions-title">Recent observed transactions</h3></div>
              <p>Current history · selecting a payment returns to its strict point-in-time investigation.</p>
            </div>
            {data.recent_transactions.length ? <div className="entity-transaction-list">{data.recent_transactions.map((transaction) => <article key={transaction.transaction_id}><div><code>{shortId(transaction.transaction_id)}</code><time>{formatTime(transaction.event_time)}</time></div><strong>{formatAmount(transaction.amount_paise, transaction.currency)}</strong><span>{transaction.status.replaceAll("_", " ")}</span><div className="entity-transaction-risk"><span>{transaction.model_score === null ? "Pending" : transaction.model_score.toFixed(3)}</span><ActionBadge action={transaction.action} /></div><button onClick={() => onInvestigate(transaction)} type="button">Investigate payment <ArrowRight size={13} /></button></article>)}</div> : <div className="entity-empty-context"><SearchX size={16} /> No persisted transactions are linked to this entity.</div>}
          </section>
        </>
      )}
    </section>
  );
}
