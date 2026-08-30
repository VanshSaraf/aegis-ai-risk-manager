import type { PolicyAction, RiskSeverity } from "@/lib/api";

const actionStyles: Record<PolicyAction, string> = {
  ALLOW: "badge-allow",
  VERIFY: "badge-verify",
  HOLD: "badge-hold",
  ESCALATE: "badge-escalate",
  RECOMMEND_BLOCK: "badge-block",
};

export function ActionBadge({ action }: { action: PolicyAction | null }) {
  if (!action) return <span className="status-badge badge-pending">Not assessed</span>;
  return (
    <span className={`status-badge ${actionStyles[action]}`}>
      {action === "RECOMMEND_BLOCK" ? "Recommend block" : action.toLowerCase()}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: RiskSeverity | null }) {
  if (!severity) return <span className="text-xs text-[var(--muted)]">—</span>;
  return <span className={`severity severity-${severity.toLowerCase()}`}>{severity}</span>;
}
