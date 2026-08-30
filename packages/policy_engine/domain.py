from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.core.enums import PolicyAction, RiskSeverity


class RuntimePolicyModel(BaseModel):
    """Strict runtime policy contract; evaluation truth is structurally unavailable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class GraphEvidence(RuntimePolicyModel):
    code: str
    strength: float = Field(ge=0, le=1)
    observed_value: float
    threshold: float
    evidence: dict[str, Any] = Field(default_factory=dict)


class RiskAssessment(RuntimePolicyModel):
    transaction_public_id: str
    model_version: str
    model_score: float = Field(ge=0, le=1)
    feature_version: str
    graph_version: str
    graph_structure_score: float = Field(ge=0, le=1)
    graph_signals: tuple[GraphEvidence, ...] = ()
    detected_cluster_id: str | None = None
    severity: RiskSeverity
    rule_signals: tuple[str, ...] = ()
    policy_context: dict[str, Any]
    computed_at: datetime


class PolicyDecisionResult(RuntimePolicyModel):
    transaction_public_id: str
    policy_version: str
    action: PolicyAction
    severity: RiskSeverity
    requires_human_review: bool
    reason_codes: tuple[str, ...]
    model_score: float = Field(ge=0, le=1)
    graph_corroborated: bool
    detected_cluster_id: str | None = None


class PolicyInput(RuntimePolicyModel):
    transaction_public_id: str
    model_version: str
    model_score: float = Field(ge=0, le=1)
    feature_version: str
    graph_version: str
    graph_structure_score: float = Field(ge=0, le=1)
    graph_signals: tuple[GraphEvidence, ...] = ()
    detected_cluster_id: str | None = None
    computed_at: datetime
