"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Database,
  GitBranch,
  FlaskConical,
  Play,
  RefreshCw,
  SearchX,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";

import { ActionBadge, SeverityBadge } from "@/components/action-badge";
import {
  EntityExplorer,
  type EntityReference,
} from "@/components/entity-explorer";
import { GraphPanel } from "@/components/graph-panel";
import {
  ApiError,
  createDemoSession,
  getDashboardSummary,
  getEntityIntelligence,
  getInvestigation,
  getTransactionGraph,
  getTransactions,
  stepDemoSession,
  type DashboardSummary,
  type DashboardTransaction,
  type DemoSession,
  type DemoStep,
  type EntityIntelligence,
  type InvestigationReport,
  type PolicyAction,
  type TransactionGraph,
} from "@/lib/api";
import { humanizeSignal, technicalSignalCode } from "@/lib/presentation";

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

function RiskBar({ score }: { score: number }) {
  return (
    <span className="risk-bar" aria-hidden="true">
      <i style={{ width: `${Math.max(2, Math.min(100, score * 100))}%` }} />
    </span>
  );
}

function EvidenceCard({ item }: { item: InvestigationReport["evidence"][number] }) {
  const technicalCode = technicalSignalCode(item.code);
  const title = item.category === "GRAPH" ? humanizeSignal(item.code, item.title) : item.title;

  return (
    <article className={item.category === "GRAPH" ? "emerging-evidence" : undefined}>
      <div className="evidence-card-topline">
        <span className={`evidence-category category-${item.category.toLowerCase()}`}>{item.category}</span>
        <span className="evidence-importance">Evidence weight {item.importance}</span>
      </div>
      <div className="evidence-card-copy">
        <strong>{title}</strong>
        <p>{item.context}</p>
      </div>
      <div className="evidence-card-source">
        <code>{technicalCode} · {item.source_version}</code>
        <span className="evidence-weight"><i style={{ width: `${Math.min(100, Math.max(0, item.importance))}%` }} /></span>
      </div>
    </article>
  );
}

function PolicyBand({ report }: { report: InvestigationReport }) {
  const score = report.model.score;
  const verify = report.policy.verify_threshold;
  const hold = report.policy.hold_threshold;
  return (
    <div className="policy-band" aria-label="Frozen model-score policy bands">
      <div className="policy-band-labels">
        <span>Allow</span><span>Verify</span><span>Hold</span>
      </div>
      <div className="policy-band-track">
        <i className="band-allow" style={{ width: `${verify * 100}%` }} />
        <i className="band-verify" style={{ left: `${verify * 100}%`, width: `${(hold - verify) * 100}%` }} />
        <i className="band-hold" style={{ left: `${hold * 100}%`, width: `${(1 - hold) * 100}%` }} />
        <b className="policy-score-marker" style={{ left: `${score * 100}%` }}><span>{score.toFixed(3)}</span></b>
      </div>
      <div className="policy-band-thresholds">
        <span>VERIFY {verify.toFixed(4)}</span><span>HOLD {hold.toFixed(4)}</span>
      </div>
      <p>Escalation is evaluated separately from score bands and requires graph corroboration.</p>
    </div>
  );
}

function RelationshipSummary({ graph }: { graph: TransactionGraph | null }) {
  if (!graph) return null;
  const types = ["CUSTOMER", "DEVICE", "PAYMENT_INSTRUMENT", "IP_ADDRESS", "ADDRESS"];
  const counts = Object.fromEntries(
    types.map((type) => [type, graph.nodes.filter((node) => node.type === type).length]),
  );
  const nodeTypes = new Map(graph.nodes.map((node) => [node.id, node.type]));
  const meaningful = graph.edges
    .filter((edge) => edge.type !== "INVOLVES")
    .sort((a, b) => {
      const rank = (edge: typeof a) => edge.type === "SEEN_ON" ? 0 : nodeTypes.get(edge.source) === "DEVICE" || nodeTypes.get(edge.target) === "DEVICE" ? 1 : 2;
      return rank(a) - rank(b);
    })
    .slice(0, 4);
  return (
    <div className="relationship-summary">
      <div className="relationship-scope">
        <span>Visible customers<strong>{counts.CUSTOMER}</strong></span>
        <span>Devices<strong>{counts.DEVICE}</strong></span>
        <span>Instruments<strong>{counts.PAYMENT_INSTRUMENT}</strong></span>
        <span>IPs<strong>{counts.IP_ADDRESS}</strong></span>
        <span>Addresses<strong>{counts.ADDRESS}</strong></span>
        <span>Relationships<strong>{graph.edges.length}</strong></span>
      </div>
      <p className="scope-note">Visible point-in-time neighborhood · bounded to {graph.max_nodes} nodes and {graph.max_edges} edges</p>
      {meaningful.length > 0 && <div className="important-relationships">
        {meaningful.map((edge) => <div key={edge.id}><code>{shortId(edge.source)}</code><span>{edge.type.replaceAll("_", " ").toLowerCase()}</span><code>{shortId(edge.target)}</code></div>)}
      </div>}
    </div>
  );
}

function DecisionProvenance({ report }: { report: InvestigationReport }) {
  const stages = [
    ["Event ingested", "accepted", report.provenance.event_received_at],
    ["Feature snapshot", report.versions.feature_version, report.provenance.feature_computed_at],
    ["Graph assessment", report.versions.graph_version, report.provenance.graph_computed_at],
    ["Model prediction", report.versions.model_version, report.provenance.prediction_created_at],
    ["Policy decision", report.versions.policy_version, report.provenance.decision_created_at],
    ["Evidence built", report.generated_by.toLowerCase(), report.generated_at],
  ];
  return <div className="provenance-trace">{stages.map(([label, version, timestamp], index) => (
    <div className="provenance-stage" key={label}>
      <span>{label}</span><strong>{version}</strong><time>{formatTime(timestamp)}</time>
      {index < stages.length - 1 && <ArrowDown size={12} />}
    </div>
  ))}</div>;
}

function InvestigationPanel({
  transaction,
  report,
  graph,
  loading,
  error,
  onRetry,
}: {
  transaction: DashboardTransaction | null;
  report: InvestigationReport | null;
  graph: TransactionGraph | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (!transaction) {
    return <section className="panel investigation-panel"><div className="panel-state tall"><SearchX size={25} /><strong>No investigation selected</strong><span>Select an assessed payment from the queue to review its decision, evidence, and strictly-prior history.</span></div></section>;
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

  const keyEvidence = report.evidence.filter((item) => item.category !== "GRAPH");
  const relationshipEvidence = report.evidence.filter((item) => item.category === "GRAPH");
  const activeObservation = graph?.signals[0]
    ? humanizeSignal(graph.signals[0].code, graph.signals[0].label)
    : "No named structural signal was present in the frozen assessment.";

  return (
    <section className="panel investigation-panel" aria-labelledby="investigation-title">
      <div className="panel-heading">
        <div>
          <div className="eyebrow"><ShieldCheck size={13} /> Investigator workspace</div>
          <h2 id="investigation-title">Why this payment needs attention</h2>
        </div>
        <ActionBadge action={report.policy.action} />
      </div>

      <div className="explanation-origin">
        {report.generated_by === "DETERMINISTIC" ? <CheckCircle2 size={14} /> : <Sparkles size={14} />}
        {report.generated_by === "DETERMINISTIC" ? "Deterministic evidence explanation" : "AI-assisted narrative"}
      </div>

      <div className="investigation-lead">
        <p className="investigation-summary">{report.summary}</p>
        <div className="score-grid" aria-label="Decision summary">
          <div><span>Model risk score</span><strong>{report.model.score.toFixed(3)}</strong><RiskBar score={report.model.score} /><small>Uncalibrated ranking score</small></div>
          <div><span>Structural coordination score</span><strong>{report.graph.structural_score.toFixed(3)}</strong><RiskBar score={report.graph.structural_score} /><small>Relationship structure · not probability</small></div>
          <div><span>Policy action</span><ActionBadge action={report.policy.action} /><SeverityBadge severity={report.policy.severity} /><small>{report.policy.requires_human_review ? "Human review required" : "Bounded policy action"}</small></div>
        </div>
      </div>

      <div className="decision-intelligence">
        <div className="decision-anatomy">
          <div className="section-kicker">Decision anatomy</div>
          <div className="anatomy-flow">
            <article><span>Behavioral model</span><strong>{report.model.score.toFixed(3)}</strong><small>{report.model.version}</small></article>
            <ArrowRight size={16} />
            <article><span>Policy band</span><strong>{report.model.score < report.policy.verify_threshold ? "ALLOW" : report.model.score < report.policy.hold_threshold ? "VERIFY" : "HOLD"}</strong><small>Score eligibility</small></article>
            <ArrowRight size={16} />
            <article><span>Structural signals</span><strong>{report.graph.signals.length} observed</strong><small>Evaluated separately</small></article>
            <ArrowRight size={16} />
            <article className="anatomy-action"><span>Final action</span><ActionBadge action={report.policy.action} /><small>Frozen policy result</small></article>
          </div>
          <PolicyBand report={report} />
        </div>
        <div className="decision-questions">
          <article><span>Why this action?</span><p>{report.decision_explanation}</p></article>
          <article><span>Why not stronger?</span><p>{report.why_not_stronger}</p></article>
        </div>
      </div>

      <div className="investigation-body">
        <div className="investigation-column">
          <div className="investigation-section">
            <h3>Relationship summary</h3>
            <RelationshipSummary graph={graph} />
          </div>

          <div className="investigation-section reasoning-layers">
            <h3>Observation → interpretation → action</h3>
            <div><span>Observation</span><p>{activeObservation}</p></div>
            <div><span>Interpretation</span><p>{report.graph_narrative}</p></div>
            <div><span>Action</span><p>{report.recommended_next_step}</p></div>
          </div>

          <div className="investigation-section">
            <h3>Key decision evidence</h3>
            <div className="evidence-list">
              {keyEvidence.map((item) => <EvidenceCard key={item.code} item={item} />)}
            </div>
          </div>

          <div className="investigation-section relationship-section">
            <h3>Relationship evidence</h3>
            <div className="evidence-list evidence-grid">
              {relationshipEvidence.map((item) => <EvidenceCard key={item.code} item={item} />)}
            </div>
          </div>
        </div>
        <aside className="investigation-aside">
          <div className="investigation-section narrative-block">
            <h3>Decision provenance</h3>
            <DecisionProvenance report={report} />
          </div>

          <div className="next-step">
            <div><span>Recommended next step</span><strong>{report.recommended_next_step}</strong></div>
            <ArrowRight size={18} />
          </div>

          <div className="investigation-section timeline-section">
            <h3>Known before this payment</h3>
            <div className="current-payment-time"><span>Current payment</span><time>{formatTime(transaction.event_time)}</time><code>{shortId(transaction.transaction_id)}</code></div>
            <p className="timeline-trust"><strong>Investigation cutoff &lt; {formatTime(transaction.event_time)}</strong>Only information available before this payment is included · {report.timeline.length} prior events shown.</p>
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

          <details className="limitations" open><summary>Current boundaries</summary><ul>{report.limitations.slice(0, 3).map((item) => <li key={item}>{item}</li>)}</ul></details>
        </aside>
      </div>
    </section>
  );
}

export function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [transactions, setTransactions] = useState<DashboardTransaction[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedOverride, setSelectedOverride] = useState<DashboardTransaction | null>(null);
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
  const [entityPath, setEntityPath] = useState<EntityReference[]>([]);
  const [entityData, setEntityData] = useState<EntityIntelligence | null>(null);
  const [entityLoading, setEntityLoading] = useState(false);
  const [entityError, setEntityError] = useState<string | null>(null);
  const [demoSession, setDemoSession] = useState<DemoSession | null>(null);
  const [latestDemoStep, setLatestDemoStep] = useState<DemoStep | null>(null);
  const [demoStatus, setDemoStatus] = useState("Ready for a deterministic showcase.");
  const [demoError, setDemoError] = useState<string | null>(null);
  const [demoRunning, setDemoRunning] = useState(false);
  const dashboardRequestGeneration = useRef(0);
  const selectionRequestGeneration = useRef(0);
  const selectedOverrideRef = useRef<DashboardTransaction | null>(null);
  const entityRequestGeneration = useRef(0);
  const demoRunGeneration = useRef(0);

  const selected = useMemo(
    () =>
      transactions.find((transaction) => transaction.transaction_id === selectedId) ??
      (selectedOverride?.transaction_id === selectedId ? selectedOverride : null),
    [selectedId, selectedOverride, transactions],
  );
  const activeEntity = entityPath.at(-1) ?? null;

  const loadDashboard = useCallback(async (
    preferredSelectedId?: string,
    filterOverride?: PolicyAction | null,
  ) => {
    const requestGeneration = ++dashboardRequestGeneration.current;
    setSummaryLoading(true);
    setTransactionsLoading(true);
    setSummaryError(null);
    setTransactionsError(null);
    const [summaryResult, transactionsResult] = await Promise.allSettled([
      getDashboardSummary(),
      getTransactions(filterOverride === undefined ? filter : filterOverride),
    ]);
    if (requestGeneration !== dashboardRequestGeneration.current) return;
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
        preferredSelectedId && items.some((item) => item.transaction_id === preferredSelectedId)
          ? preferredSelectedId
          : items.some((item) => item.transaction_id === current)
          ? current
          : selectedOverrideRef.current?.transaction_id === current
          ? current
          : (items.find((item) => item.assessed)?.transaction_id ?? items[0]?.transaction_id ?? null),
      );
    } else {
      setTransactionsError("The transaction queue is unavailable.");
    }
    setTransactionsLoading(false);
  }, [filter]);

  const runDemo = useCallback(async (activeSession: DemoSession, generation: number) => {
    setDemoRunning(true);
    setDemoError(null);
    let expectedStep = activeSession.next_step;
    try {
      while (expectedStep < activeSession.total_steps) {
        if (demoRunGeneration.current !== generation) return;
        setDemoStatus(`Injecting coordinated activity · ${expectedStep} / ${activeSession.total_steps}`);
        const result = await stepDemoSession(activeSession.session_id, expectedStep);
        if (demoRunGeneration.current !== generation) return;
        setLatestDemoStep(result);
        expectedStep = result.step;
        setDemoSession((current) => current ? { ...current, next_step: result.step } : current);
        if (result.transaction) {
          await loadDashboard(result.transaction.public_id, null);
        }
        if (result.complete) break;
        await new Promise((resolve) => window.setTimeout(resolve, 650));
      }
      if (demoRunGeneration.current === generation) {
        setDemoStatus("Scenario complete · latest investigation is open.");
      }
    } catch (reason) {
      if (demoRunGeneration.current === generation) {
        setDemoError(reason instanceof Error ? reason.message : "Demo step failed.");
        setDemoStatus("Demo paused — retry step.");
      }
    } finally {
      if (demoRunGeneration.current === generation) setDemoRunning(false);
    }
  }, [loadDashboard]);

  const startDemo = useCallback(async () => {
    if (demoRunning) return;
    const generation = ++demoRunGeneration.current;
    setFilter(null);
    setDemoRunning(true);
    setDemoError(null);
    setLatestDemoStep(null);
    setDemoStatus("Preparing baseline...");
    try {
      const started = await createDemoSession();
      if (demoRunGeneration.current !== generation) return;
      setDemoSession(started);
      setDemoStatus(`Baseline established · ${started.baseline_transactions} transactions assessed.`);
      await loadDashboard(undefined, null);
      await new Promise((resolve) => window.setTimeout(resolve, 650));
      await runDemo(started, generation);
    } catch (reason) {
      if (demoRunGeneration.current === generation) {
        setDemoError(reason instanceof ApiError && reason.status === 404 ? "Demo mode is disabled. Set AEGIS_DEMO_MODE=true on the API." : reason instanceof Error ? reason.message : "Demo setup failed.");
        setDemoStatus("Demo unavailable.");
        setDemoRunning(false);
      }
    }
  }, [demoRunning, loadDashboard, runDemo]);

  const retryDemo = useCallback(() => {
    if (!demoSession || demoRunning) return;
    const generation = ++demoRunGeneration.current;
    void runDemo(demoSession, generation);
  }, [demoRunning, demoSession, runDemo]);

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

  const loadEntity = useCallback(async () => {
    const requestGeneration = ++entityRequestGeneration.current;
    if (!activeEntity) {
      setEntityData(null);
      setEntityError(null);
      setEntityLoading(false);
      return;
    }
    setEntityLoading(true);
    setEntityError(null);
    try {
      const result = await getEntityIntelligence(
        activeEntity.entityType,
        activeEntity.publicId,
      );
      if (requestGeneration === entityRequestGeneration.current) setEntityData(result);
    } catch (reason) {
      if (requestGeneration === entityRequestGeneration.current) {
        setEntityData(null);
        setEntityError(
          reason instanceof Error ? reason.message : "Entity request failed.",
        );
      }
    } finally {
      if (requestGeneration === entityRequestGeneration.current) setEntityLoading(false);
    }
  }, [activeEntity]);

  const exploreEntity = useCallback((reference: EntityReference) => {
    setEntityPath((current) => [...current, reference].slice(-6));
  }, []);

  const closeEntity = useCallback(() => {
    entityRequestGeneration.current += 1;
    setEntityPath([]);
    setEntityData(null);
    setEntityError(null);
  }, []);

  const investigateEntityTransaction = useCallback(
    (transaction: DashboardTransaction) => {
      setFilter(null);
      selectedOverrideRef.current = transaction;
      setSelectedOverride(transaction);
      setTransactions((current) => [
        transaction,
        ...current.filter((item) => item.transaction_id !== transaction.transaction_id),
      ].slice(0, 50));
      setSelectedId(transaction.transaction_id);
      closeEntity();
      window.setTimeout(
        () => document.getElementById("selected-payment-workspace")?.scrollIntoView({ behavior: "smooth" }),
        0,
      );
    },
    [closeEntity],
  );

  useEffect(() => {
    const task = window.setTimeout(() => void loadDashboard(), 0);
    return () => {
      window.clearTimeout(task);
      dashboardRequestGeneration.current += 1;
    };
  }, [loadDashboard]);
  useEffect(() => {
    const task = window.setTimeout(() => void loadSelection(), 0);
    return () => {
      window.clearTimeout(task);
      selectionRequestGeneration.current += 1;
    };
  }, [loadSelection]);
  useEffect(() => {
    const task = window.setTimeout(() => void loadEntity(), 0);
    return () => {
      window.clearTimeout(task);
      entityRequestGeneration.current += 1;
    };
  }, [loadEntity]);
  useEffect(() => () => {
    demoRunGeneration.current += 1;
  }, []);

  const flaggedCount = summary
    ? summary.verify_count + summary.hold_count + summary.escalate_count + summary.recommend_block_count
    : null;
  const highRiskCount = summary
    ? summary.hold_count + summary.escalate_count + summary.recommend_block_count
    : null;
  const activeSignalCount = new Set(transactions.flatMap((transaction) => transaction.graph_signals)).size;
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
            <div><div className="eyebrow">Payment risk intelligence</div><h1>Aegis</h1><p>Risk Operations</p></div>
          </div>
          <div className="topbar-actions">
            <nav className="app-nav" aria-label="Primary navigation">
              <Link href="/" className="active"><Activity size={13} /> Operations</Link>
              <Link href="/evaluation"><FlaskConical size={13} /> Evaluation Lab</Link>
            </nav>
            <div className="system-state">
              <span className={`connection-dot ${connected ? "connected" : "unavailable"}`} />
              <div><strong>{connected ? "Backend connected" : "Backend unavailable"}</strong><span>{summary?.model_version ?? "risk-lgbm-v2"} · {summary?.policy_version ?? "risk-policy-v2"}</span></div>
              <button aria-label="Refresh dashboard" title="Refresh dashboard" onClick={() => void loadDashboard()}><RefreshCw size={15} className={dashboardLoading ? "spin" : ""} /></button>
            </div>
          </div>
        </header>

        {summaryError && <div className="section-error summary-error"><AlertTriangle size={16} /><span>{summaryError}</span><button onClick={() => void loadDashboard()}>Retry summary</button></div>}

        <section className="metrics-grid" aria-label="Operational summary">
          <MetricCard label="Transactions monitored" value={summary?.transaction_count ?? null} detail={`${summary?.assessed_count ?? 0} assessed`} icon={<Database size={18} />} tone="tone-blue" loading={summaryLoading} />
          <MetricCard label="Interventions" value={flaggedCount} detail="Verify or stronger" icon={<Activity size={18} />} tone="tone-amber" loading={summaryLoading} />
          <MetricCard label="Active structural signals" value={activeSignalCount} detail="Across the loaded queue" icon={<GitBranch size={18} />} tone="tone-purple" loading={transactionsLoading} />
          <MetricCard label="High-risk decisions" value={highRiskCount} detail="Hold or stronger" icon={<AlertTriangle size={18} />} tone="tone-red" loading={summaryLoading} />
        </section>

        {activeEntity ? (
          <EntityExplorer
            path={entityPath}
            data={entityData}
            loading={entityLoading}
            error={entityError}
            onPivot={exploreEntity}
            onBack={() => setEntityPath((current) => current.slice(0, -1))}
            onBreadcrumb={(index) => setEntityPath((current) => current.slice(0, index + 1))}
            onClose={closeEntity}
            onRetry={() => void loadEntity()}
            onInvestigate={investigateEntityTransaction}
          />
        ) : (
          <>
        <div className="operations-layout">
          <aside className="operations-rail">
            <section className={`demo-console ${demoRunning ? "running" : ""}`} aria-label="Synthetic traffic simulation">
              <div className="demo-intro"><div className="eyebrow"><Zap size={13} /> Synthetic traffic simulation</div><h2>Inject a coordinated abuse ring</h2><p>Sends synthetic payment events through the same Aegis ingestion and risk pipeline.</p></div>
              <div className="demo-progress">
                <div className="demo-progress-copy"><span>{demoStatus}</span><strong>{demoSession ? `${demoSession.next_step} / ${demoSession.total_steps}` : "Identity rotation"}</strong></div>
                <div className="demo-progress-track"><i style={{ width: `${demoSession ? (demoSession.next_step / demoSession.total_steps) * 100 : 0}%` }} /></div>
                {latestDemoStep?.assessment && <div className="demo-latest"><div><span>Model risk score</span><strong>{latestDemoStep.assessment.model_score.toFixed(3)}</strong><small>Uncalibrated</small></div><div><span>Policy action</span><ActionBadge action={latestDemoStep.assessment.action} /></div><div><span>Signals</span><strong>{latestDemoStep.assessment.graph_signal_count}</strong><small>Structural</small></div></div>}
                {demoError && <div className="demo-error"><AlertTriangle size={14} /><span>{demoError}</span>{demoSession && <button onClick={retryDemo}>Retry step</button>}</div>}
              </div>
              <button className="inject-button" disabled={demoRunning} onClick={() => void startDemo()}><Play size={16} fill="currentColor" />{demoRunning ? "Injecting traffic…" : demoSession && demoSession.next_step === demoSession.total_steps ? "Run new simulation" : "Inject abuse ring"}</button>
            </section>

            <section className="panel transaction-panel" aria-labelledby="transactions-title">
              <div className="panel-heading transaction-heading">
                <div><div className="eyebrow"><Activity size={13} /> Monitoring queue</div><h2 id="transactions-title">Recent payments</h2></div>
                <span className="queue-count">{transactions.length} loaded</span>
              </div>
              <div className="filters" aria-label="Filter transactions by action">
                {filters.map((item) => <button key={item.label} className={filter === item.value ? "active" : ""} onClick={() => setFilter(item.value)}>{item.label}</button>)}
              </div>
              <div className="table-wrap queue-scroll">
                {transactionsError && <div className="section-error transaction-error"><AlertTriangle size={16} /><span>{transactionsError}</span><button onClick={() => void loadDashboard()}>Retry queue</button></div>}
                <table className="transaction-table">
                  <thead><tr><th>Payment</th><th>Amount</th><th>Risk</th><th>Decision</th><th>Context</th><th>Time</th></tr></thead>
                  <tbody>
                    {transactionsLoading && transactions.length === 0 ? Array.from({ length: 6 }, (_, index) => <tr key={index} className="table-loading"><td colSpan={6}><div className="skeleton" /></td></tr>) : transactions.map((transaction) => (
                      <tr
                        key={transaction.transaction_id}
                        className={selectedId === transaction.transaction_id ? "selected" : ""}
                        tabIndex={0}
                        aria-selected={selectedId === transaction.transaction_id}
                        onClick={() => {
                          selectedOverrideRef.current = null;
                          setSelectedOverride(null);
                          setSelectedId(transaction.transaction_id);
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            selectedOverrideRef.current = null;
                            setSelectedOverride(null);
                            setSelectedId(transaction.transaction_id);
                          }
                        }}
                      >
                        <td><div className="payment-cell"><code>{shortId(transaction.transaction_id)}</code><small>{shortId(transaction.customer_id)}</small></div></td>
                        <td className="amount">{formatAmount(transaction.amount_paise, transaction.currency)}</td>
                        <td>{transaction.model_score === null ? <span className="pending-copy">Pending</span> : <div className="score-cell"><strong>{transaction.model_score.toFixed(3)}</strong><RiskBar score={transaction.model_score} /></div>}</td>
                        <td><div className="decision-cell"><ActionBadge action={transaction.action} /><SeverityBadge severity={transaction.severity} /></div></td>
                        <td>{transaction.graph_signals.length ? <span className="graph-indicator"><GitBranch size={12} />{transaction.graph_signals.length} signal{transaction.graph_signals.length > 1 ? "s" : ""}</span> : <span className="muted-copy">No signals</span>}</td>
                        <td><time>{formatTime(transaction.event_time)}</time></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!transactionsLoading && !transactionsError && transactions.length === 0 && <div className="empty-table"><Database size={25} /><strong>No transactions yet</strong><span>{filter ? "No recent payments match this action filter." : "Send a payment event or run the synthetic traffic simulation."}</span></div>}
              </div>
            </section>
          </aside>

          <section id="selected-payment-workspace" className="graph-workspace" aria-label="Selected payment workspace">
            {selected ? (
              <section className="selected-strip" aria-label="Selected transaction details">
                <div className="selected-identity"><span>Investigating payment</span><strong>{formatAmount(selected.amount_paise, selected.currency)}</strong><code>{selected.transaction_id}</code></div>
                <div className="selected-risk"><span>Model risk score</span><strong>{selected.model_score?.toFixed(3) ?? "Pending"}</strong>{selected.model_score !== null && <RiskBar score={selected.model_score} />}</div>
                <ActionBadge action={selected.action} />
                <dl>
                  <div><dt>Customer</dt><dd>{shortId(selected.customer_id)}</dd></div>
                  <div><dt>Merchant</dt><dd>{shortId(selected.merchant_id)}</dd></div>
                  <div><dt>Time</dt><dd>{formatTime(selected.event_time)}</dd></div>
                </dl>
              </section>
            ) : (
              <section className="selected-strip selected-empty" aria-label="No selected transaction"><span>Select a payment from the queue to begin an investigation.</span></section>
            )}
            <GraphPanel graph={graph} loading={loadingSelection} error={graphError} onRetry={() => void loadSelection()} onExploreEntity={(entityType, publicId) => exploreEntity({ entityType, publicId })} />
          </section>
        </div>

        <InvestigationPanel transaction={selected} report={investigation} graph={graph} loading={loadingSelection} error={investigationError} onRetry={() => void loadSelection()} />
          </>
        )}
        <footer><span>Aegis provides bounded risk recommendations for human review.</span><span>Model and graph evidence do not confirm fraud.</span></footer>
      </div>
    </main>
  );
}
