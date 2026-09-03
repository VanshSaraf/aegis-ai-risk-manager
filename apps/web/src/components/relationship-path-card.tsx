import { ArrowDown, ArrowRight, GitBranch, X } from "lucide-react";

import {
  relationshipPathInterpretation,
  relationshipStepLabel,
  type RelationshipPath,
  type VisibleGraphNode,
} from "@/lib/relationship-path";

function nodeTypeLabel(type: string): string {
  return type
    .replace("TRANSACTION", "PAYMENT")
    .replace("PAYMENT_INSTRUMENT", "PAYMENT INSTRUMENT")
    .replace("IP_ADDRESS", "IP ADDRESS")
    .replaceAll("_", " ");
}

function shortId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-6)}` : value;
}

export function RelationshipPathCard({
  path,
  context,
  onClear,
  onEntityAction,
  canEntityAction,
  entityActionLabel,
  signalNote,
}: {
  path: RelationshipPath | null;
  context: "POINT_IN_TIME" | "CURRENT_OBSERVED_HISTORY";
  onClear: () => void;
  onEntityAction?: (node: VisibleGraphNode) => void;
  canEntityAction?: (node: VisibleGraphNode) => boolean;
  entityActionLabel?: string;
  signalNote?: string | null;
}) {
  const contextLabel =
    context === "POINT_IN_TIME"
      ? "Point-in-time relationship path"
      : "Current-history relationship path";

  return (
    <section className="relationship-path-card" aria-label="Relationship path explanation">
      <header>
        <div>
          <div className="eyebrow"><GitBranch size={13} /> Relationship path intelligence</div>
          <h3>Why are these identities connected?</h3>
        </div>
        <button className="clear-path-button" onClick={onClear} type="button">
          <X size={12} /> Clear path
        </button>
      </header>
      {!path ? (
        <div className="relationship-path-empty">
          <strong>No connection exists inside the visible bounded network.</strong>
          <span>This does not imply that no connection exists outside the loaded graph.</span>
        </div>
      ) : (
        <>
          <div className="relationship-path-summary">
            <strong>{path.edges.length} hop{path.edges.length === 1 ? "" : "s"}</strong>
            <span>{path.nodes.length} entit{path.nodes.length === 1 ? "y" : "ies"}</span>
            <span>{contextLabel}</span>
            <span>Path within visible network</span>
          </div>
          <div className="relationship-path-chain">
            {path.nodes.map((node, index) => (
              <div className="relationship-path-segment" key={node.id}>
                {index > 0 && (
                  <div className="relationship-path-link">
                    <ArrowRight size={14} />
                    <span>{relationshipStepLabel(path.edges[index - 1], path.nodes[index - 1], node)}</span>
                    <code>{path.edges[index - 1].type}</code>
                  </div>
                )}
                <article className="relationship-path-node">
                  <span>{nodeTypeLabel(node.type)}</span>
                  <code title={node.id}>{shortId(node.id)}</code>
                  {onEntityAction &&
                    node.type !== "TRANSACTION" &&
                    (canEntityAction?.(node) ?? true) && (
                    <button
                      onClick={() => onEntityAction(node)}
                      type="button"
                    >
                      {entityActionLabel ?? "Explore entity"} <ArrowRight size={11} />
                    </button>
                  )}
                </article>
              </div>
            ))}
          </div>
          <div className="relationship-path-meaning">
            <ArrowDown size={13} />
            <p>{relationshipPathInterpretation(path)}</p>
          </div>
          {signalNote && <p className="relationship-path-signal">{signalNote}</p>}
        </>
      )}
    </section>
  );
}
