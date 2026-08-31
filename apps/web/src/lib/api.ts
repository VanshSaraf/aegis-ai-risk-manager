export type PolicyAction =
  | "ALLOW"
  | "VERIFY"
  | "HOLD"
  | "ESCALATE"
  | "RECOMMEND_BLOCK";

export type RiskSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface DashboardSummary {
  transaction_count: number;
  assessed_count: number;
  allow_count: number;
  verify_count: number;
  hold_count: number;
  escalate_count: number;
  recommend_block_count: number;
  active_cluster_count: number;
  model_version: string;
  policy_version: string;
}

export interface DashboardTransaction {
  transaction_id: string;
  event_time: string;
  amount_paise: number;
  currency: string;
  payment_method: string;
  customer_id: string;
  merchant_id: string;
  instrument_id: string;
  device_id: string;
  ip_id: string;
  address_id: string;
  assessed: boolean;
  model_score: number | null;
  model_version: string | null;
  action: PolicyAction | null;
  severity: RiskSeverity | null;
  requires_human_review: boolean | null;
  graph_signals: string[];
  cluster_id: string | null;
}

export interface DashboardTransactionList {
  items: DashboardTransaction[];
  limit: number;
}

export interface EvidenceItem {
  code: string;
  category: "TRANSACTION" | "BEHAVIOR" | "VELOCITY" | "GRAPH" | "POLICY" | "CLUSTER";
  title: string;
  observed_value: string | number | boolean | null;
  context: string;
  importance: number;
  source: string;
  source_version: string;
}

export interface TimelineEntry {
  transaction_id: string;
  event_time: string;
  summary: string;
  entity_references: Record<string, string>;
}

export interface InvestigationReport {
  transaction_id: string;
  generated_by: "DETERMINISTIC" | "LLM";
  llm_status: "DISABLED" | "AVAILABLE" | "UNAVAILABLE" | "INVALID_RESPONSE";
  summary: string;
  decision_explanation: string;
  graph_narrative: string;
  narrative: string | null;
  evidence: EvidenceItem[];
  timeline: TimelineEntry[];
  recommended_next_step: string;
  limitations: string[];
  model: { version: string; score: number; semantics: string };
  policy: {
    version: string;
    action: PolicyAction;
    severity: RiskSeverity;
    requires_human_review: boolean;
    reason_codes: string[];
  };
  graph: {
    version: string;
    structural_score: number;
    signals: string[];
    selected_metrics: Record<string, string | number | boolean | null>;
  };
  cluster: {
    cluster_id: string;
    context: string;
    point_in_time_counts_available: boolean;
  } | null;
  generated_at: string;
}

export interface TransactionGraph {
  transaction_id: string;
  nodes: Array<{
    id: string;
    type: string;
    label: string;
    is_current: boolean;
    connection_count: number;
  }>;
  edges: Array<{ id: string; source: string; target: string; type: string }>;
  signals: Array<{ code: string; label: string }>;
  cluster_id: string | null;
  has_prior_relationships: boolean;
  max_nodes: number;
  max_edges: number;
}

export interface DemoSession {
  session_id: string;
  scenario: {
    code: "IDENTITY_ROTATION";
    display_name: string;
    description: string;
  };
  baseline_transactions: number;
  total_steps: number;
  next_step: number;
}

export interface DemoStep {
  session_id: string;
  step: number;
  total_steps: number;
  complete: boolean;
  transaction: {
    public_id: string;
    amount_paise: number;
    event_time: string;
  } | null;
  assessment: {
    model_score: number;
    model_score_semantics: string;
    action: PolicyAction;
    severity: RiskSeverity;
    graph_signal_count: number;
    cluster_id: string | null;
  } | null;
}

export interface EvaluationMetrics {
  pr_auc: number;
  precision: number;
  recall: number;
  f1: number;
  false_positive: number;
  false_negative: number;
  threshold: number;
}

export interface EvaluationSummary {
  benchmark: {
    evaluation_type: string;
    dataset_version: string;
    generator_version: string;
    seed: number;
    transaction_count: number;
    legitimate_count: number;
    coordinated_abuse_count: number;
    model_version: string;
  };
  models: Array<{ code: string; display_name: string; metrics: EvaluationMetrics }>;
  external_model: { code: string; display_name: string; metrics: EvaluationMetrics };
  external_seed: number;
  external_dataset_version: string;
  policy_external: {
    policy_version: string;
    abuse_intervention_recall: number;
    legitimate_intervention_rate: number;
    legitimate_severe_intervention_rate: number;
    total_human_review_rate: number;
    allowed_abuse_transactions: number;
    constraints_generalized: boolean;
    validation_legitimate_intervention_budget: number;
    estimated_net_protected_value_paise: number;
    cost_assumptions_label: string;
  };
  methodology: string[];
  limitations: string[];
  artifact_sources: string[];
}

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Keep the status-based fallback for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const value = (await response.json()) as { detail?: string };
      detail = value.detail ?? detail;
    } catch {
      // Keep the status-based fallback for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return getJson("/api/v1/dashboard/summary");
}

export function getTransactions(
  action: PolicyAction | null = null,
): Promise<DashboardTransactionList> {
  const query = new URLSearchParams({ limit: "50" });
  if (action) query.set("action", action);
  return getJson(`/api/v1/dashboard/transactions?${query.toString()}`);
}

export function getInvestigation(transactionId: string): Promise<InvestigationReport> {
  return getJson(`/api/v1/transactions/${encodeURIComponent(transactionId)}/investigation`);
}

export function getTransactionGraph(transactionId: string): Promise<TransactionGraph> {
  return getJson(`/api/v1/transactions/${encodeURIComponent(transactionId)}/graph`);
}

export function createDemoSession(): Promise<DemoSession> {
  return postJson("/api/v1/demo/sessions", { scenario: "IDENTITY_ROTATION" });
}

export function stepDemoSession(sessionId: string, expectedStep: number): Promise<DemoStep> {
  return postJson(`/api/v1/demo/sessions/${encodeURIComponent(sessionId)}/step`, {
    expected_step: expectedStep,
  });
}

export function getEvaluationSummary(): Promise<EvaluationSummary> {
  return getJson("/api/v1/evaluation/summary");
}
