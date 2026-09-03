from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.core.enums import PolicyAction, RiskSeverity


class InvestigatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceCategory(StrEnum):
    TRANSACTION = "TRANSACTION"
    BEHAVIOR = "BEHAVIOR"
    VELOCITY = "VELOCITY"
    GRAPH = "GRAPH"
    POLICY = "POLICY"
    CLUSTER = "CLUSTER"


type EvidenceValue = str | int | float | bool


class EntityReferences(InvestigatorModel):
    customer: str
    merchant: str
    instrument: str
    device: str
    ip: str
    address: str


class TransactionSummary(InvestigatorModel):
    transaction_id: str
    event_time: datetime
    amount_paise: int = Field(ge=0)
    formatted_amount: str
    currency: str
    payment_method: str
    entities: EntityReferences


class ModelSummary(InvestigatorModel):
    version: str
    score: float = Field(ge=0, le=1)
    semantics: str = "uncalibrated risk ranking score; not a fraud probability"


class PolicySummary(InvestigatorModel):
    version: str
    action: PolicyAction
    severity: RiskSeverity
    requires_human_review: bool
    reason_codes: tuple[str, ...]
    verify_threshold: float = Field(ge=0, le=1)
    hold_threshold: float = Field(ge=0, le=1)
    graph_corroborated: bool
    strong_signal_codes: tuple[str, ...]
    escalation_minimum_strong_signals: int = Field(ge=1)
    recommend_block_minimum_strong_signals: int = Field(ge=1)
    recommend_block_requires_active_cluster: bool


class GraphSummary(InvestigatorModel):
    version: str
    structural_score: float = Field(ge=0, le=1)
    signals: tuple[str, ...]
    selected_metrics: dict[str, EvidenceValue]


class EvidenceItem(InvestigatorModel):
    code: str
    category: EvidenceCategory
    title: str
    observed_value: EvidenceValue
    context: str
    importance: int = Field(ge=1, le=100)
    source: str
    source_version: str


class RelatedEntity(InvestigatorModel):
    entity_type: str
    public_id: str
    connections: dict[str, int] = Field(default_factory=dict)
    context: str


class ClusterContext(InvestigatorModel):
    cluster_id: str
    context: str
    point_in_time_counts_available: bool = False


class TimelineEntry(InvestigatorModel):
    transaction_id: str
    event_time: datetime
    summary: str
    entity_references: dict[str, str]


class VersionMetadata(InvestigatorModel):
    feature_version: str
    graph_version: str
    model_version: str
    policy_version: str


class DecisionProvenance(InvestigatorModel):
    event_received_at: datetime
    feature_computed_at: datetime
    feature_max_source_event_time: datetime | None
    graph_computed_at: datetime
    graph_max_source_event_time: datetime | None
    prediction_created_at: datetime
    decision_created_at: datetime


class EvidenceBundle(InvestigatorModel):
    transaction: TransactionSummary
    model: ModelSummary
    policy: PolicySummary
    graph: GraphSummary
    evidence_items: tuple[EvidenceItem, ...]
    related_entities: tuple[RelatedEntity, ...]
    cluster: ClusterContext | None
    timeline: tuple[TimelineEntry, ...]
    limitations: tuple[str, ...]
    versions: VersionMetadata
    provenance: DecisionProvenance


class GeneratedBy(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    LLM = "LLM"


class LLMStatus(StrEnum):
    DISABLED = "DISABLED"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class InvestigationReport(InvestigatorModel):
    transaction_id: str
    generated_by: GeneratedBy
    llm_status: LLMStatus
    summary: str
    decision_explanation: str
    why_not_stronger: str
    graph_narrative: str
    narrative: str | None = None
    evidence: tuple[EvidenceItem, ...]
    related_entities: tuple[RelatedEntity, ...]
    cluster: ClusterContext | None
    timeline: tuple[TimelineEntry, ...]
    recommended_next_step: str
    limitations: tuple[str, ...]
    model: ModelSummary
    policy: PolicySummary
    graph: GraphSummary
    versions: VersionMetadata
    provenance: DecisionProvenance
    generated_at: datetime
