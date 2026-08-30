import json
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.enums import ClusterStatus
from apps.api.app.core.ids import generate_public_id
from apps.api.app.core.time import utc_now
from apps.api.app.models import (
    AbuseCluster,
    AuditEvent,
    ClusterMember,
    DatasetVersion,
    ModelVersion,
    PolicyDecision,
    RiskPrediction,
    RiskSignal,
    Transaction,
)
from packages.graph_engine.postgres import row_to_graph_transaction
from packages.graph_engine.service import compute_graph_for_transaction
from packages.policy_engine.config import PolicyConfig, load_policy_config
from packages.policy_engine.domain import (
    GraphEvidence,
    PolicyDecisionResult,
    PolicyInput,
    RiskAssessment,
)
from packages.policy_engine.engine import PolicyEngine
from packages.risk_engine.features.postgres import transaction_history_query
from packages.risk_engine.features.service import compute_for_transaction
from packages.risk_engine.model import RiskModel

MODEL_ARTIFACT_DIRECTORY = Path(__file__).parents[2] / "ml/artifacts/model-v2"


class AssessmentConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AssessmentServiceResult:
    risk_prediction_id: str
    policy_decision_id: str
    assessment: RiskAssessment
    decision: PolicyDecisionResult
    latency_ms: dict[str, float]


@lru_cache(maxsize=4)
def _load_model(path: str) -> RiskModel:
    return RiskModel.load(Path(path))


async def _ensure_model_registry(session: AsyncSession, artifact_directory: Path) -> None:
    metadata = json.loads((artifact_directory / "metadata.json").read_text(encoding="utf-8"))
    benchmark = json.loads((artifact_directory / "benchmark.json").read_text(encoding="utf-8"))
    dataset = benchmark["dataset"]
    dataset_version = str(metadata["benchmark_dataset_version"])
    existing_dataset = await session.get(DatasetVersion, dataset_version)
    if existing_dataset is None:
        session.add(
            DatasetVersion(
                version=dataset_version,
                generator_version=str(dataset["generator_version"]),
                seed=int(dataset["seed"]),
                config={
                    "config_hash": dataset["config_hash"],
                    "source": "frozen model-v2 benchmark artifact",
                },
                transaction_count=int(dataset["transaction_count"]),
                legitimate_count=int(dataset["legitimate_count"]),
                abuse_count=int(dataset["coordinated_abuse_count"]),
            )
        )
        await session.flush()
    existing_model = await session.get(ModelVersion, str(metadata["model_version"]))
    expected = {
        "model_type": str(metadata["model_type"]),
        "artifact_path": str(artifact_directory),
        "feature_version": str(metadata["feature_version"]),
        "training_dataset_version": dataset_version,
        "threshold": float(metadata["selected_threshold"]),
        "metrics": {
            "output_semantics": metadata["model_output_semantics"],
            "validation": metadata["validation_metrics"],
            "test": metadata["test_metrics"],
            "graph_version": metadata["graph_version"],
        },
    }
    if existing_model is None:
        session.add(ModelVersion(version=str(metadata["model_version"]), **expected))
        await session.flush()
    elif any(getattr(existing_model, key) != value for key, value in expected.items()):
        raise AssessmentConflictError("registered risk-lgbm-v2 metadata does not match artifact")


async def _active_cluster_id(session: AsyncSession, transaction_public_id: str) -> str | None:
    row = (
        await session.execute(
            transaction_history_query().where(Transaction.public_id == transaction_public_id)
        )
    ).one()
    entities = {entity.public_id for entity in row_to_graph_transaction(row).entities()}
    statement = (
        select(AbuseCluster)
        .join(ClusterMember, ClusterMember.cluster_id == AbuseCluster.id)
        .where(
            AbuseCluster.status.in_((ClusterStatus.OPEN, ClusterStatus.UNDER_REVIEW)),
            ClusterMember.entity_public_id.in_(entities),
        )
        .group_by(AbuseCluster.id)
        .having(func.count(ClusterMember.id) >= 2)
        .order_by(AbuseCluster.cluster_score.desc(), AbuseCluster.public_id)
    )
    cluster = await session.scalar(statement)
    return cluster.public_id if cluster else None


async def _persist_prediction(
    session: AsyncSession,
    transaction: Transaction,
    assessment: RiskAssessment,
    inference_latency_ms: int,
) -> tuple[RiskPrediction, bool]:
    existing = await session.scalar(
        select(RiskPrediction).where(
            RiskPrediction.transaction_id == transaction.id,
            RiskPrediction.model_version == assessment.model_version,
        )
    )
    semantic = (
        assessment.feature_version,
        assessment.graph_version,
        assessment.model_score,
        assessment.graph_structure_score,
    )
    if existing is not None:
        persisted = (
            existing.feature_version,
            existing.graph_version,
            existing.ml_score,
            existing.graph_score,
        )
        if persisted != semantic or existing.fused_score is not None or existing.top_features != []:
            raise AssessmentConflictError("immutable risk prediction mismatch")
        return existing, False
    prediction = RiskPrediction(
        transaction_id=transaction.id,
        model_version=assessment.model_version,
        feature_version=assessment.feature_version,
        graph_version=assessment.graph_version,
        ml_score=assessment.model_score,
        graph_score=assessment.graph_structure_score,
        fused_score=None,
        severity=None,
        top_features=[],
        inference_latency_ms=inference_latency_ms,
    )
    session.add(prediction)
    await session.flush()
    return prediction, True


async def _persist_signals(
    session: AsyncSession,
    transaction: Transaction,
    assessment: RiskAssessment,
    policy: PolicyConfig,
) -> None:
    values = {
        signal: {
            "model_score": assessment.model_score,
            "graph_structure_score": assessment.graph_structure_score,
            "policy_version": policy.policy_version,
        }
        for signal in assessment.rule_signals
    }
    for code, value in values.items():
        existing = await session.scalar(
            select(RiskSignal).where(
                RiskSignal.transaction_id == transaction.id,
                RiskSignal.signal_code == code,
                RiskSignal.rule_version == policy.policy_version,
            )
        )
        if existing is None:
            session.add(
                RiskSignal(
                    transaction_id=transaction.id,
                    signal_code=code,
                    severity=assessment.severity,
                    value=value,
                    rule_version=policy.policy_version,
                )
            )
        elif existing.severity != assessment.severity or existing.value != value:
            raise AssessmentConflictError("immutable risk signal mismatch")


async def _persist_decision(
    session: AsyncSession,
    transaction: Transaction,
    prediction: RiskPrediction,
    decision: PolicyDecisionResult,
) -> tuple[PolicyDecision, bool]:
    reason = {
        "reason_codes": list(decision.reason_codes),
        "severity": decision.severity.value,
        "model_score_semantics": "uncalibrated score; not a fraud probability",
        "graph_corroborated": decision.graph_corroborated,
        "detected_cluster_id": decision.detected_cluster_id,
    }
    existing = await session.scalar(
        select(PolicyDecision).where(
            PolicyDecision.transaction_id == transaction.id,
            PolicyDecision.policy_version == decision.policy_version,
        )
    )
    if existing is not None:
        comparable = (
            existing.risk_prediction_id,
            existing.action,
            existing.decision_reason,
            existing.requires_human_review,
        )
        expected = (prediction.id, decision.action, reason, decision.requires_human_review)
        if comparable != expected:
            raise AssessmentConflictError("immutable policy decision mismatch")
        return existing, False
    persisted = PolicyDecision(
        public_id=generate_public_id("dec"),
        transaction_id=transaction.id,
        risk_prediction_id=prediction.id,
        policy_version=decision.policy_version,
        action=decision.action,
        decision_reason=reason,
        requires_human_review=decision.requires_human_review,
    )
    session.add(persisted)
    await session.flush()
    return persisted, True


async def assess_transaction(
    session: AsyncSession,
    transaction_public_id: str,
    *,
    policy: PolicyConfig | None = None,
    artifact_directory: Path = MODEL_ARTIFACT_DIRECTORY,
) -> AssessmentServiceResult:
    total_started = time.perf_counter()
    transaction = await session.scalar(
        select(Transaction).where(Transaction.public_id == transaction_public_id)
    )
    if transaction is None:
        raise LookupError("transaction not found")
    feature_started = time.perf_counter()
    feature_vector = await compute_for_transaction(session, transaction_public_id, persist=True)
    feature_ms = (time.perf_counter() - feature_started) * 1000
    graph_started = time.perf_counter()
    graph = await compute_graph_for_transaction(session, transaction_public_id, persist=True)
    graph_ms = (time.perf_counter() - graph_started) * 1000

    await _ensure_model_registry(session, artifact_directory)
    model = _load_model(str(artifact_directory))
    inference_started = time.perf_counter()
    prediction = model.predict(feature_vector.values, graph.metrics)
    inference_ms = (time.perf_counter() - inference_started) * 1000
    policy_config = policy or load_policy_config()
    cluster_id = await _active_cluster_id(session, transaction_public_id)
    policy_input = PolicyInput(
        transaction_public_id=transaction_public_id,
        model_version=prediction.model_version,
        model_score=prediction.score,
        feature_version=feature_vector.feature_version,
        graph_version=graph.graph_version,
        graph_structure_score=graph.structural_score,
        graph_signals=tuple(
            GraphEvidence.model_validate(signal.as_dict()) for signal in graph.signals
        ),
        detected_cluster_id=cluster_id,
        computed_at=utc_now(),
    )
    policy_started = time.perf_counter()
    assessment, decision = PolicyEngine(policy_config).assess(policy_input)
    policy_ms = (time.perf_counter() - policy_started) * 1000
    persisted_prediction, prediction_created = await _persist_prediction(
        session, transaction, assessment, round(inference_ms)
    )
    await _persist_signals(session, transaction, assessment, policy_config)
    persisted_decision, decision_created = await _persist_decision(
        session, transaction, persisted_prediction, decision
    )
    if prediction_created:
        session.add(
            AuditEvent(
                public_id=generate_public_id("aud"),
                aggregate_type="RISK_PREDICTION",
                aggregate_id=str(persisted_prediction.id),
                event_type="RISK_PREDICTION_CREATED",
                actor_type="SYSTEM",
                actor_id=None,
                payload={
                    "transaction_public_id": transaction_public_id,
                    "model_version": assessment.model_version,
                    "feature_version": assessment.feature_version,
                    "graph_version": assessment.graph_version,
                },
            )
        )
    if decision_created:
        session.add(
            AuditEvent(
                public_id=generate_public_id("aud"),
                aggregate_type="POLICY_DECISION",
                aggregate_id=persisted_decision.public_id,
                event_type="POLICY_DECISION_CREATED",
                actor_type="SYSTEM",
                actor_id=None,
                payload={
                    "transaction_public_id": transaction_public_id,
                    "policy_version": decision.policy_version,
                    "action": decision.action.value,
                    "severity": decision.severity.value,
                    "reason_codes": list(decision.reason_codes),
                    "requires_human_review": decision.requires_human_review,
                },
            )
        )
    await session.commit()
    total_ms = (time.perf_counter() - total_started) * 1000
    return AssessmentServiceResult(
        risk_prediction_id=str(persisted_prediction.id),
        policy_decision_id=persisted_decision.public_id,
        assessment=assessment,
        decision=decision,
        latency_ms={
            "feature_computation": feature_ms,
            "graph_computation": graph_ms,
            "model_inference": inference_ms,
            "policy_evaluation": policy_ms,
            "total": total_ms,
        },
    )
