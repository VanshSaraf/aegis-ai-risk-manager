"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Database,
  GitBranch,
  RefreshCw,
  SearchX,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { ActionBadge, SeverityBadge } from "@/components/action-badge";
import { GraphPanel } from "@/components/graph-panel";
import {
  getDashboardSummary,
  getInvestigation,
  getTransactionGraph,
  getTransactions,
  type DashboardSummary,
  type DashboardTransaction,
  type InvestigationReport,
  type PolicyAction,
  type TransactionGraph,
} from "@/lib/api";

const filters: Array<{ label: string; value: PolicyAction | null }> = [
  { label: "All", value: null },
  { label: "Allow", value: "ALLOW" },
  { label: "Verify", value: "VERIFY" },
  { label: "Hold", value: "HOLD" },
  { label: "Escalate", value: "ESCALATE" },
  { label: "Recommend block", value: "RECOMMEND_BLOCK" },
];

function formatAmount(amountPaise: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amountPaise / 100);
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "short",
  }).format(new Date(value));
}

function shortId(value: string): string {
  return `${value.slice(0, 7)}…${value.slice(-5)}`;
}

function MetricCard({
  label,
  value,
  detail,
  icon,
  tone,
  loading,
}: {
  label: string;
  value: number | null;
  detail: string;
  icon: React.ReactNode;
  tone: string;
  loading: boolean;
}) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}>{icon}</div>
      <div>
        <p>{label}</p>
        {loading ? (
          <div className="skeleton metric-skeleton" />
        ) : (
          <strong>{value === null ? "—" : value.toLocaleString("en-IN")}</strong>
        )}
        <span>{detail}</span>
      </div>
    </article>
  );
}

function InvestigationPanel({
  transaction,
  report,
  loading,
  error,
  onRetry,
}: {
  transaction: DashboardTransaction | null;
  report: InvestigationReport | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (!transaction) {
    return <section className="panel investigation-panel"><div className="panel-state tall"><SearchX size={25} /><span>Select a transaction to review its evidence.</span></div></section>;
  }
  if (!transaction.assessed) {
    return (
      <section className="panel investigation-panel">
        <div className="panel-heading"><div><div className="eyebrow"><Clock3 size={13} /> Investigation</div><h2>Assessment pending</h2></div><ActionBadge action={null} /></div>
        <div className="panel-state tall"><Clock3 size={25} /><strong>Risk evidence is not available yet</strong><span>This transaction has been ingested but has not been assessed. Aegis will not fabricate model or graph findings.</span></div>
      </section>
    );
  }
  if (loading) return <section className="panel investigation-panel"><div className="skeleton investigation-skeleton" /></section>;
  if (error || !report) {
    return <section className="panel investigation-panel"><div className="panel-state tall"><AlertTriangle size={25} /><strong>Investigation unavailable</strong><span>{error ?? "No report was returned."}</span><button onClick={onRetry}>Retry investigation</button></div></section>;
  }

  return (
    <section className="panel investigation-panel" aria-labelledby="investigation-title">
      <div className="panel-heading">
        <div>
          <div className="eyebrow"><ShieldCheck size={13} /> Why Aegis flagged this</div>
          <h2 id="investigation-title">Decision investigation</h2>
        </div>
        <ActionBadge action={report.policy.action} />
      </div>

      <div className="explanation-origin">
        {report.generated_by === "DETERMINISTIC" ? <CheckCircle2 size={14} /> : <Sparkles size={14} />}
        {report.generated_by === "DETERMINISTIC" ? "Deterministic evidence explanation" : "AI-assisted narrative"}
      </div>

      <p className="investigation-summary">{report.summary}</p>

      <div className="score-grid">
        <div><span>Model score</span><strong>{report.model.score.toFixed(3)}</strong><small>Uncalibrated risk score</small></div>
        <div><span>Graph score</span><strong>{report.graph.structural_score.toFixed(3)}</strong><small>Structural evidence</small></div>
        <div><span>Severity</span><SeverityBadge severity={report.policy.severity} /><small>{report.policy.requires_human_review ? "Human review required" : "Bounded policy action"}</small></div>
      </div>

      <div className="investigation-section">
        <h3>Top evidence</h3>
        <div className="evidence-list">
          {report.evidence.slice(0, 5).map((item) => (
            <article key={item.code}>
              <span className={`evidence-category category-${item.category.toLowerCase()}`}>{item.category}</span>
              <div><strong>{item.title}</strong><p>{item.context}</p></div>
              <code>{String(item.observed_value)}</code>
            </article>
          ))}
        </div>
      </div>

      <div className="investigation-section narrative-block">
        <h3>Policy explanation</h3>
        <p>{report.decision_explanation}</p>
        <p>{report.graph_narrative}</p>
      </div>

      <div className="next-step">
        <div><span>Recommended next step</span><strong>{report.recommended_next_step}</strong></div>
        <ArrowRight size={18} />
      </div>

      <div className="investigation-section">
        <h3>Recent related activity</h3>
        {report.timeline.length === 0 ? (
          <p className="muted-copy">No strictly-prior related transactions were found.</p>
        ) : (
          <ol className="timeline">
            {report.timeline.map((item) => (
              <li key={item.transaction_id}><i /><div><time>{formatTime(item.event_time)}</time><p>{item.summary}</p><code>{shortId(item.transaction_id)}</code></div></li>
            ))}
          </ol>
        )}
      </div>

      {report.cluster && (
        <div className="cluster-context"><GitBranch size={16} /><div><span>Structural investigation cluster</span><code>{report.cluster.cluster_id}</code></div></div>
      )}

      <details className="limitations"><summary>Evidence limitations</summary><ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
    </section>
  );
}

export function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [transactions, setTransactions] = useState<DashboardTransaction[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<PolicyAction | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [transactionsLoading, setTransactionsLoading] = useState(true);
  const [transactionsError, setTransactionsError] = useState<string | null>(null);
  const [investigation, setInvestigation] = useState<InvestigationReport | null>(null);
  const [graph, setGraph] = useState<TransactionGraph | null>(null);
  const [loadingSelection, setLoadingSelection] = useState(false);
  const [investigationError, setInvestigationError] = useState<string | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const selectionRequestGeneration = useRef(0);

  const selected = useMemo(
    () => transactions.find((transaction) => transaction.transaction_id === selectedId) ?? null,
    [selectedId, transactions],
  );

  const loadDashboard = useCallback(async () => {
    setSummaryLoading(true);
    setTransactionsLoading(true);
    setSummaryError(null);
    setTransactionsError(null);
    const [summaryResult, transactionsResult] = await Promise.allSettled([
      getDashboardSummary(),
      getTransactions(filter),
    ]);
    if (summaryResult.status === "fulfilled") {
      setSummary(summaryResult.value);
    } else {
      setSummaryError("Operational summary is unavailable.");
    }
    setSummaryLoading(false);
    if (transactionsResult.status === "fulfilled") {
      const items = transactionsResult.value.items;
      setTransactions(items);
      setSelectedId((current) =>
        items.some((item) => item.transaction_id === current)
          ? current
          : (items.find((item) => item.assessed)?.transaction_id ?? items[0]?.transaction_id ?? null),
      );
    } else {
      setTransactionsError("The transaction queue is unavailable.");
    }
    setTransactionsLoading(false);
  }, [filter]);

  const loadSelection = useCallback(async () => {
    const requestGeneration = ++selectionRequestGeneration.current;
    if (!selectedId || !selected?.assessed) {
      setInvestigation(null);
      setGraph(null);
      setInvestigationError(null);
      setGraphError(null);
      setLoadingSelection(false);
      return;
    }
    setLoadingSelection(true);
    setInvestigationError(null);
    setGraphError(null);
    const [investigationResult, graphResult] = await Promise.allSettled([
      getInvestigation(selectedId),
      getTransactionGraph(selectedId),
    ]);
    if (requestGeneration !== selectionRequestGeneration.current) return;
    if (investigationResult.status === "fulfilled") setInvestigation(investigationResult.value);
    else {
      setInvestigation(null);
      setInvestigationError(investigationResult.reason instanceof Error ? investigationResult.reason.message : "Investigation request failed.");
    }
    if (graphResult.status === "fulfilled") setGraph(graphResult.value);
    else {
      setGraph(null);
      setGraphError(graphResult.reason instanceof Error ? graphResult.reason.message : "Graph request failed.");
    }
    setLoadingSelection(false);
  }, [selected, selectedId]);

  useEffect(() => {
    const task = window.setTimeout(() => void loadDashboard(), 0);
    return () => window.clearTimeout(task);
  }, [loadDashboard]);
  useEffect(() => {
    const task = window.setTimeout(() => void loadSelection(), 0);
    return () => {
      window.clearTimeout(task);
      selectionRequestGeneration.current += 1;
    };
  }, [loadSelection]);

  const flaggedCount = summary
    ? summary.verify_count + summary.hold_count + summary.escalate_count + summary.recommend_block_count
    : null;
  const highRiskCount = summary
    ? summary.hold_count + summary.escalate_count + summary.recommend_block_count
    : null;
  const connected =
    !(summaryError && transactionsError) &&
    (summary !== null || (!transactionsLoading && transactionsError === null));
  const dashboardLoading = summaryLoading || transactionsLoading;

  return (
    <main className="dashboard-shell">
      <div className="dashboard-frame">
        <header className="topbar">
          <div className="brand-lockup">
            <span className="brand-mark">A</span>
            <div><div className="eyebrow">Risk operations</div><h1>Aegis</h1><p>Graph-assisted payment risk intelligence</p></div>
          </div>
          <div className="system-state">
            <span className={`connection-dot ${connected ? "connected" : "unavailable"}`} />
            <div><strong>{connected ? "Backend connected" : "Backend unavailable"}</strong><span>{summary?.model_version ?? "risk-lgbm-v2"} · {summary?.policy_version ?? "risk-policy-v2"}</span></div>
            <button aria-label="Refresh dashboard" title="Refresh dashboard" onClick={() => void loadDashboard()}><RefreshCw size={15} className={dashboardLoading ? "spin" : ""} /></button>
          </div>
        </header>

        {summaryError && <div className="section-error summary-error"><AlertTriangle size={16} /><span>{summaryError}</span><button onClick={() => void loadDashboard()}>Retry summary</button></div>}

        <section className="metrics-grid" aria-label="Operational summary">
          <MetricCard label="Transactions monitored" value={summary?.transaction_count ?? null} detail={`${summary?.assessed_count ?? 0} assessed`} icon={<Database size={18} />} tone="tone-blue" loading={summaryLoading} />
          <MetricCard label="Flagged for review" value={flaggedCount} detail="Verify or stronger" icon={<Activity size={18} />} tone="tone-amber" loading={summaryLoading} />
          <MetricCard label="High-risk decisions" value={highRiskCount} detail="Hold or stronger" icon={<AlertTriangle size={18} />} tone="tone-red" loading={summaryLoading} />
          <MetricCard label="Structural clusters" value={summary?.active_cluster_count ?? null} detail="Open or under review" icon={<GitBranch size={18} />} tone="tone-purple" loading={summaryLoading} />
        </section>

        <section className="panel transaction-panel" aria-labelledby="transactions-title">
          <div className="panel-heading transaction-heading">
            <div><div className="eyebrow"><Activity size={13} /> Monitoring queue</div><h2 id="transactions-title">Recent transactions</h2></div>
            <div className="filters" aria-label="Filter transactions by action">
              {filters.map((item) => <button key={item.label} className={filter === item.value ? "active" : ""} onClick={() => setFilter(item.value)}>{item.label}</button>)}
            </div>
          </div>
          <div className="table-wrap">
            {transactionsError && <div className="section-error transaction-error"><AlertTriangle size={16} /><span>{transactionsError}</span><button onClick={() => void loadDashboard()}>Retry queue</button></div>}
            <table>
              <thead><tr><th>Time</th><th>Transaction</th><th>Amount</th><th>Customer</th><th>Model score</th><th>Action</th><th>Severity</th><th>Graph</th></tr></thead>
              <tbody>
                {transactionsLoading && transactions.length === 0 ? Array.from({ length: 4 }, (_, index) => <tr key={index} className="table-loading"><td colSpan={8}><div className="skeleton" /></td></tr>) : transactions.map((transaction) => (
                  <tr
                    key={transaction.transaction_id}
                    className={selectedId === transaction.transaction_id ? "selected" : ""}
                    tabIndex={0}
                    onClick={() => setSelectedId(transaction.transaction_id)}
                    onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedId(transaction.transaction_id); }}
                  >
                    <td><time>{formatTime(transaction.event_time)}</time></td>
                    <td><code>{shortId(transaction.transaction_id)}</code></td>
                    <td className="amount">{formatAmount(transaction.amount_paise, transaction.currency)}</td>
                    <td><code>{shortId(transaction.customer_id)}</code></td>
                    <td>{transaction.model_score === null ? <span className="pending-copy">Pending</span> : <div className="score-cell"><strong>{transaction.model_score.toFixed(3)}</strong><span>uncalibrated</span></div>}</td>
                    <td><ActionBadge action={transaction.action} /></td>
                    <td><SeverityBadge severity={transaction.severity} /></td>
                    <td>{transaction.graph_signals.length ? <span className="graph-indicator"><GitBranch size={12} />{transaction.graph_signals.length} signal{transaction.graph_signals.length > 1 ? "s" : ""}</span> : <span className="muted-copy">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!transactionsLoading && !transactionsError && transactions.length === 0 && <div className="empty-table"><Database size={25} /><strong>No transactions found</strong><span>{filter ? "No recent transactions match this action filter." : "Ingest transactions to populate the monitoring queue."}</span></div>}
          </div>
        </section>

        {selected && (
          <section className="selected-strip" aria-label="Selected transaction details">
            <div><span>Selected transaction</span><code>{selected.transaction_id}</code></div>
            <dl>
              <div><dt>Customer</dt><dd>{shortId(selected.customer_id)}</dd></div>
              <div><dt>Device</dt><dd>{shortId(selected.device_id)}</dd></div>
              <div><dt>Instrument</dt><dd>{shortId(selected.instrument_id)}</dd></div>
              <div><dt>IP</dt><dd>{shortId(selected.ip_id)}</dd></div>
              <div><dt>Address</dt><dd>{shortId(selected.address_id)}</dd></div>
            </dl>
          </section>
        )}

        <div className="workspace-grid">
          <GraphPanel graph={graph} loading={loadingSelection} error={graphError} onRetry={() => void loadSelection()} />
          <InvestigationPanel transaction={selected} report={investigation} loading={loadingSelection} error={investigationError} onRetry={() => void loadSelection()} />
        </div>
        <footer><span>Aegis provides bounded risk recommendations for human review.</span><span>Model and graph evidence do not confirm fraud.</span></footer>
      </div>
    </main>
  );
}
