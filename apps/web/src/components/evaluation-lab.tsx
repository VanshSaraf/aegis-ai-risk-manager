"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  FlaskConical,
  GitCompareArrows,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { getEvaluationSummary, type EvaluationSummary } from "@/lib/api";

function percent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function metric(value: number): string {
  return value.toFixed(4);
}

export function EvaluationLab() {
  const [summary, setSummary] = useState<EvaluationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await getEvaluationSummary());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Evaluation summary unavailable.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, []);

  const combined = summary?.models.find((item) => item.code === "COMBINED")?.metrics;

  return (
    <main className="dashboard-shell evaluation-shell">
      <div className="dashboard-frame evaluation-frame">
        <header className="topbar">
          <div className="brand-lockup">
            <span className="brand-mark">A</span>
            <div><div className="eyebrow">Measured evidence</div><h1>Evaluation Lab</h1><p>Frozen benchmark results and operating-policy discipline</p></div>
          </div>
          <nav className="app-nav" aria-label="Primary navigation">
            <Link href="/"><ArrowLeft size={13} /> Operations</Link>
            <Link href="/evaluation" className="active"><FlaskConical size={13} /> Evaluation Lab</Link>
          </nav>
        </header>

        {error && <div className="section-error evaluation-error"><AlertTriangle size={16} /><span>{error}</span><button onClick={() => void load()}>Retry</button></div>}
        {loading && !summary && <div className="evaluation-loading skeleton" />}

        {summary && (
          <>
            <section className="evaluation-hero">
              <div>
                <div className="benchmark-badge"><ShieldCheck size={13} /> Held-out synthetic evaluation</div>
                <h2>Relationship evidence changes the risk picture.</h2>
                <p>Metrics are measured on frozen synthetic benchmarks and are not production or Razorpay performance claims.</p>
              </div>
              <dl className="benchmark-meta">
                <div><dt>Dataset</dt><dd>{summary.benchmark.dataset_version}</dd></div>
                <div><dt>Test seed</dt><dd>{summary.benchmark.seed}</dd></div>
                <div><dt>Transactions</dt><dd>{summary.benchmark.transaction_count.toLocaleString("en-IN")}</dd></div>
                <div><dt>Submission model</dt><dd>{summary.benchmark.model_version}</dd></div>
              </dl>
            </section>

            <section className="evaluation-metrics" aria-label="Combined model metrics">
              <article><span>Combined PR-AUC</span><strong>{combined ? metric(combined.pr_auc) : "—"}</strong><small>Best held-out ranking result</small></article>
              <article><span>Precision</span><strong>{combined ? metric(combined.precision) : "—"}</strong><small>At validation-selected threshold</small></article>
              <article><span>Recall</span><strong>{combined ? metric(combined.recall) : "—"}</strong><small>Frozen test partition</small></article>
              <article><span>False positives</span><strong>{combined?.false_positive ?? "—"}</strong><small>Frozen test partition</small></article>
            </section>

            <section className="evaluation-grid">
              <article className="panel comparison-panel">
                <div className="panel-heading"><div><div className="eyebrow"><GitCompareArrows size={13} /> Model comparison</div><h2>Tabular vs graph vs combined</h2></div><span className="frozen-chip">Frozen test</span></div>
                <div className="comparison-content">
                  <div className="comparison-legend"><span>PR-AUC</span><span>FP / FN</span></div>
                  {summary.models.map((item) => (
                    <div className={`comparison-row comparison-${item.code.toLowerCase()}`} key={item.code}>
                      <div><strong>{item.display_name}</strong><small>{item.code === "COMBINED" ? "risk-lgbm-v2" : `${item.display_name.toLowerCase()} ablation`}</small></div>
                      <div className="bar-track"><i style={{ width: `${item.metrics.pr_auc * 100}%` }} /></div>
                      <code>{metric(item.metrics.pr_auc)}</code>
                      <span>{item.metrics.false_positive} / {item.metrics.false_negative}</span>
                    </div>
                  ))}
                  <div className="comparison-table">
                    <div><span>Model</span><span>Precision</span><span>Recall</span><span>F1</span></div>
                    {summary.models.map((item) => <div key={item.code}><strong>{item.display_name}</strong><code>{metric(item.metrics.precision)}</code><code>{metric(item.metrics.recall)}</code><code>{metric(item.metrics.f1)}</code></div>)}
                  </div>
                  <p className="interpretation"><BarChart3 size={15} /> Relationship structure materially improved held-out ranking and reduced false-positive behavior versus tabular-only scoring. Graph-only retained the strongest thresholded recall/F1; combined achieved the highest PR-AUC and lowest false-positive count.</p>
                </div>
              </article>

              <article className="panel external-panel">
                <div className="panel-heading"><div><div className="eyebrow"><FlaskConical size={13} /> Fresh external check</div><h2>Seed {summary.external_seed}</h2></div><span className="frozen-chip">No retuning</span></div>
                <div className="external-body">
                  <div className="external-score"><span>Combined PR-AUC</span><strong>{metric(summary.external_model.metrics.pr_auc)}</strong><small>{summary.external_dataset_version}</small></div>
                  <div className="policy-flow"><span>Model score</span><i>→</i><span>Bounded policy</span><i>→</i><span>Recommendation</span></div>
                  <h3>External policy check</h3>
                  <dl className="policy-stats">
                    <div><dt>Abuse intervention</dt><dd>{percent(summary.policy_external.abuse_intervention_recall)}</dd></div>
                    <div><dt>Legitimate intervention</dt><dd className="warning-value">{percent(summary.policy_external.legitimate_intervention_rate)}</dd></div>
                    <div><dt>Legitimate severe intervention</dt><dd>{percent(summary.policy_external.legitimate_severe_intervention_rate)}</dd></div>
                    <div><dt>Allowed abuse events</dt><dd>{summary.policy_external.allowed_abuse_transactions}</dd></div>
                  </dl>
                  <div className="honesty-note"><AlertTriangle size={15} /><p><strong>Validation budgets did not all generalize.</strong> Legitimate intervention reached {percent(summary.policy_external.legitimate_intervention_rate)} against a {percent(summary.policy_external.validation_legitimate_intervention_budget)} validation target. Thresholds were not retuned on this external holdout.</p></div>
                </div>
              </article>
            </section>

            <section className="evaluation-grid lower-grid">
              <article className="panel discipline-panel"><div className="panel-heading"><div><div className="eyebrow"><CheckCircle2 size={13} /> Evaluation discipline</div><h2>Leakage-aware methodology</h2></div></div><ul>{summary.methodology.map((item) => <li key={item}><CheckCircle2 size={13} />{item}</li>)}</ul></article>
              <article className="panel discipline-panel limitation-panel"><div className="panel-heading"><div><div className="eyebrow"><AlertTriangle size={13} /> Known boundaries</div><h2>Limitations</h2></div></div><ul>{summary.limitations.map((item) => <li key={item}><span>—</span>{item}</li>)}</ul></article>
            </section>

            <section className="economic-note"><div><span>Illustrative synthetic economics</span><strong>₹{(summary.policy_external.estimated_net_protected_value_paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</strong></div><p>Estimated net protected value under committed synthetic cost assumptions. This is not a Razorpay savings or production economic claim.</p></section>
            <footer><span>Source of truth: committed frozen artifact JSON.</span><span>{summary.artifact_sources.length} presentation-safe artifact sources · {loading ? <RefreshCw size={9} className="spin" /> : "loaded"}</span></footer>
          </>
        )}
      </div>
    </main>
  );
}
