import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.core.enums import ClusterStatus, PolicyAction, RiskSeverity
from apps.api.app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class TransactionFeature(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "transaction_features"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id",
            "feature_version",
            name="uq_transaction_features_transaction_version",
        ),
        Index("ix_transaction_features_version_transaction", "feature_version", "transaction_id"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    feature_version: Mapped[str] = mapped_column(
        String(100), ForeignKey("feature_versions.version"), nullable=False
    )
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_source_event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GraphAssessmentSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "graph_assessment_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id",
            "graph_version",
            name="uq_graph_assessments_transaction_version",
        ),
        Index("ix_graph_assessments_version_transaction", "graph_version", "transaction_id"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    graph_version: Mapped[str] = mapped_column(String(100), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signals: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    structural_score: Mapped[float] = mapped_column(Float, nullable=False)
    component_fingerprints: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    candidate_cluster: Mapped[bool] = mapped_column(Boolean, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_source_event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RiskPrediction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "risk_predictions"
    __table_args__ = (Index("ix_risk_predictions_transaction_id", "transaction_id"),)

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    model_version: Mapped[str] = mapped_column(
        String(100), ForeignKey("model_versions.version"), nullable=False
    )
    feature_version: Mapped[str] = mapped_column(
        String(100), ForeignKey("feature_versions.version"), nullable=False
    )
    ml_score: Mapped[float] = mapped_column(Float, nullable=False)
    graph_score: Mapped[float] = mapped_column(Float, nullable=False)
    fused_score: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[RiskSeverity] = mapped_column(String(32), nullable=False)
    top_features: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    inference_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class RiskSignal(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "risk_signals"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    signal_code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[RiskSeverity] = mapped_column(String(32), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(100), nullable=False)


class AbuseCluster(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "abuse_clusters"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[ClusterStatus] = mapped_column(String(32), nullable=False)
    cluster_score: Mapped[float] = mapped_column(Float, nullable=False)
    account_count: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_count: Mapped[int] = mapped_column(Integer, nullable=False)
    device_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_count: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exposure_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(100), nullable=False)


class ClusterMember(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "cluster_members"
    __table_args__ = (
        Index("ix_cluster_members_cluster_id", "cluster_id"),
        UniqueConstraint(
            "cluster_id",
            "entity_type",
            "entity_public_id",
            name="uq_cluster_members_cluster_entity",
        ),
    )

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("abuse_clusters.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    membership_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class PolicyDecision(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "policy_decisions"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    risk_prediction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_predictions.id"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[PolicyAction] = mapped_column(String(32), nullable=False)
    decision_reason: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(nullable=False)


class Investigation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "investigations"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
