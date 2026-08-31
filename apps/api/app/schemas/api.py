from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.core.enums import PolicyAction, ProcessingStatus, RiskSeverity
from apps.api.app.schemas.contracts import NormalizedTransaction


class TransactionList(BaseModel):
    items: list[NormalizedTransaction]
    limit: int
    offset: int


class Neighbor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str
    public_id: str
    relation_type: str
    direction: str
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int = Field(ge=1)


class NeighborList(BaseModel):
    entity_type: str
    public_id: str
    neighbors: list[Neighbor]


class ReadinessResponse(BaseModel):
    status: str
    database: str


class IngestionFailure(BaseModel):
    event_id: str
    processing_status: ProcessingStatus
    detail: str


class ModelScoreResponse(BaseModel):
    version: str
    score: float
    semantics: str


class GraphEvidenceResponse(BaseModel):
    version: str
    structural_score: float
    signals: list[str]
    detected_cluster_id: str | None


class RiskResponse(BaseModel):
    severity: RiskSeverity


class PolicyResponse(BaseModel):
    version: str
    action: PolicyAction
    requires_human_review: bool
    reason_codes: list[str]


class OperationalAssessmentResponse(BaseModel):
    transaction_id: str
    risk_prediction_id: str
    policy_decision_id: str
    model: ModelScoreResponse
    graph: GraphEvidenceResponse
    risk: RiskResponse
    policy: PolicyResponse
    latency_ms: dict[str, float]


class DashboardSummary(BaseModel):
    transaction_count: int = Field(ge=0)
    assessed_count: int = Field(ge=0)
    allow_count: int = Field(ge=0)
    verify_count: int = Field(ge=0)
    hold_count: int = Field(ge=0)
    escalate_count: int = Field(ge=0)
    recommend_block_count: int = Field(ge=0)
    active_cluster_count: int = Field(ge=0)
    model_version: str = "risk-lgbm-v2"
    policy_version: str = "risk-policy-v2"


class DashboardTransaction(BaseModel):
    transaction_id: str
    event_time: datetime
    amount_paise: int = Field(ge=0)
    currency: str
    payment_method: str
    customer_id: str
    merchant_id: str
    instrument_id: str
    device_id: str
    ip_id: str
    address_id: str
    assessed: bool
    model_score: float | None = None
    model_version: str | None = None
    action: PolicyAction | None = None
    severity: RiskSeverity | None = None
    requires_human_review: bool | None = None
    graph_signals: list[str] = Field(default_factory=list)
    cluster_id: str | None = None


class DashboardTransactionList(BaseModel):
    items: list[DashboardTransaction]
    limit: int


class TransactionGraphNode(BaseModel):
    id: str
    type: str
    label: str
    is_current: bool
    connection_count: int = Field(ge=0)


class TransactionGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str


class TransactionGraphSignal(BaseModel):
    code: str
    label: str


class TransactionGraphResponse(BaseModel):
    transaction_id: str
    nodes: list[TransactionGraphNode]
    edges: list[TransactionGraphEdge]
    signals: list[TransactionGraphSignal]
    cluster_id: str | None
    has_prior_relationships: bool
    max_nodes: int
    max_edges: int


class DemoScenarioRequest(BaseModel):
    scenario: Literal["IDENTITY_ROTATION"] = "IDENTITY_ROTATION"


class DemoStepRequest(BaseModel):
    expected_step: int = Field(ge=0)


class DemoScenario(BaseModel):
    code: Literal["IDENTITY_ROTATION"]
    display_name: str
    description: str


class DemoSessionResponse(BaseModel):
    session_id: str
    scenario: DemoScenario
    baseline_transactions: int = Field(ge=0)
    total_steps: int = Field(ge=1)
    next_step: int = Field(ge=0)


class DemoTransactionSummary(BaseModel):
    public_id: str
    amount_paise: int = Field(gt=0)
    event_time: datetime


class DemoAssessmentSummary(BaseModel):
    model_score: float = Field(ge=0, le=1)
    model_score_semantics: str
    action: PolicyAction
    severity: RiskSeverity
    graph_signal_count: int = Field(ge=0)
    cluster_id: str | None


class DemoStepResponse(BaseModel):
    session_id: str
    step: int = Field(ge=0)
    total_steps: int = Field(ge=1)
    complete: bool
    transaction: DemoTransactionSummary | None
    assessment: DemoAssessmentSummary | None


class EvaluationClassificationMetrics(BaseModel):
    pr_auc: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    threshold: float = Field(ge=0, le=1)


class EvaluationModelResult(BaseModel):
    code: str
    display_name: str
    metrics: EvaluationClassificationMetrics


class EvaluationBenchmark(BaseModel):
    evaluation_type: str
    dataset_version: str
    generator_version: str
    seed: int
    transaction_count: int = Field(gt=0)
    legitimate_count: int = Field(ge=0)
    coordinated_abuse_count: int = Field(ge=0)
    model_version: str


class EvaluationPolicyExternal(BaseModel):
    policy_version: str
    abuse_intervention_recall: float = Field(ge=0, le=1)
    legitimate_intervention_rate: float = Field(ge=0, le=1)
    legitimate_severe_intervention_rate: float = Field(ge=0, le=1)
    total_human_review_rate: float = Field(ge=0, le=1)
    allowed_abuse_transactions: int = Field(ge=0)
    constraints_generalized: bool
    validation_legitimate_intervention_budget: float = Field(ge=0, le=1)
    estimated_net_protected_value_paise: int
    cost_assumptions_label: str


class EvaluationSummary(BaseModel):
    benchmark: EvaluationBenchmark
    models: list[EvaluationModelResult]
    external_model: EvaluationModelResult
    external_seed: int
    external_dataset_version: str
    policy_external: EvaluationPolicyExternal
    methodology: list[str]
    limitations: list[str]
    artifact_sources: list[str]
