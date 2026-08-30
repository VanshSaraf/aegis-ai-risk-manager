from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.enums import ClusterStatus, GraphEntityType
from apps.api.app.core.ids import generate_public_id
from apps.api.app.models import (
    AbuseCluster,
    ClusterMember,
    GraphAssessmentSnapshot,
    Transaction,
)
from packages.graph_engine.clustering import membership_reason
from packages.graph_engine.domain import DetectedCluster, GraphAssessment, GraphEntityRef
from packages.graph_engine.engine import GraphEngine
from packages.graph_engine.offline import OfflineGraphResult, build_offline_graph
from packages.graph_engine.postgres import (
    PostgreSQLGraphProvider,
    row_to_graph_transaction,
)
from packages.graph_engine.registry import (
    GRAPH_METRICS,
    GRAPH_VERSION,
    SIGNAL_DEFINITIONS,
)
from packages.graph_engine.validation import validate_graph_assessment
from packages.risk_engine.features.postgres import transaction_history_query


class GraphSnapshotConflictError(ValueError):
    pass


async def _persist_assessment(
    session: AsyncSession,
    transaction: Transaction,
    assessment: GraphAssessment,
) -> GraphAssessmentSnapshot:
    signals = [signal.as_dict() for signal in assessment.signals]
    existing = await session.scalar(
        select(GraphAssessmentSnapshot).where(
            GraphAssessmentSnapshot.transaction_id == transaction.id,
            GraphAssessmentSnapshot.graph_version == assessment.graph_version,
        )
    )
    if existing is not None:
        comparable = (
            existing.metrics,
            existing.signals,
            existing.structural_score,
            existing.component_fingerprints,
            existing.candidate_cluster,
            existing.max_source_event_time,
        )
        expected = (
            assessment.metrics,
            signals,
            assessment.structural_score,
            list(assessment.touched_component_fingerprints),
            assessment.candidate_cluster,
            assessment.max_source_event_time,
        )
        if comparable != expected:
            raise GraphSnapshotConflictError(
                f"immutable graph snapshot mismatch for {transaction.public_id}"
            )
        return existing
    snapshot = GraphAssessmentSnapshot(
        transaction_id=transaction.id,
        graph_version=assessment.graph_version,
        metrics=assessment.metrics,
        signals=signals,
        structural_score=assessment.structural_score,
        component_fingerprints=list(assessment.touched_component_fingerprints),
        candidate_cluster=assessment.candidate_cluster,
        computed_at=assessment.computed_at,
        max_source_event_time=assessment.max_source_event_time,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def persist_clusters(
    session: AsyncSession,
    detections: list[DetectedCluster],
) -> list[AbuseCluster]:
    persisted: list[AbuseCluster] = []
    for detection in detections:
        cluster = await session.scalar(
            select(AbuseCluster).where(AbuseCluster.fingerprint == detection.fingerprint)
        )
        if cluster is None:
            candidates = (
                await session.scalars(
                    select(AbuseCluster).where(
                        AbuseCluster.detector_version == GRAPH_VERSION,
                        AbuseCluster.status == ClusterStatus.OPEN,
                    )
                )
            ).all()
            best_match: tuple[float, AbuseCluster] | None = None
            detected_devices = {
                member
                for member in detection.members
                if member.entity_type == GraphEntityType.DEVICE
            }
            for candidate in candidates:
                candidate_rows = (
                    await session.scalars(
                        select(ClusterMember).where(ClusterMember.cluster_id == candidate.id)
                    )
                ).all()
                candidate_members = {
                    GraphEntityRef(
                        GraphEntityType(member.entity_type),
                        member.entity_public_id,
                    )
                    for member in candidate_rows
                }
                candidate_devices = {
                    member
                    for member in candidate_members
                    if member.entity_type == GraphEntityType.DEVICE
                }
                if not detected_devices.intersection(candidate_devices):
                    continue
                overlap = len(detection.members.intersection(candidate_members)) / min(
                    len(detection.members), len(candidate_members)
                )
                if overlap >= 0.7 and (best_match is None or overlap > best_match[0]):
                    best_match = (overlap, candidate)
            if best_match is not None:
                cluster = best_match[1]
        counts = {
            entity_type: sum(member.entity_type == entity_type for member in detection.members)
            for entity_type in GraphEntityType
        }
        if cluster is None:
            cluster = AbuseCluster(
                public_id=generate_public_id("clu"),
                fingerprint=detection.fingerprint,
                status=ClusterStatus.OPEN,
                cluster_score=detection.structural_score,
                account_count=counts[GraphEntityType.CUSTOMER],
                instrument_count=counts[GraphEntityType.PAYMENT_INSTRUMENT],
                device_count=counts[GraphEntityType.DEVICE],
                ip_count=counts[GraphEntityType.IP],
                transaction_count=detection.transaction_count,
                exposure_paise=detection.exposure_paise,
                first_seen_at=detection.first_seen_at,
                last_seen_at=detection.last_seen_at,
                detector_version=GRAPH_VERSION,
            )
            session.add(cluster)
            await session.flush()
        else:
            cluster.cluster_score = detection.structural_score
            cluster.account_count = counts[GraphEntityType.CUSTOMER]
            cluster.instrument_count = counts[GraphEntityType.PAYMENT_INSTRUMENT]
            cluster.device_count = counts[GraphEntityType.DEVICE]
            cluster.ip_count = counts[GraphEntityType.IP]
            cluster.transaction_count = detection.transaction_count
            cluster.exposure_paise = detection.exposure_paise
            cluster.first_seen_at = min(cluster.first_seen_at, detection.first_seen_at)
            cluster.last_seen_at = max(cluster.last_seen_at, detection.last_seen_at)

        for member in sorted(detection.members):
            existing_member = await session.scalar(
                select(ClusterMember).where(
                    ClusterMember.cluster_id == cluster.id,
                    ClusterMember.entity_type == member.entity_type.value,
                    ClusterMember.entity_public_id == member.public_id,
                )
            )
            if existing_member is None:
                session.add(
                    ClusterMember(
                        cluster_id=cluster.id,
                        entity_type=member.entity_type.value,
                        entity_public_id=member.public_id,
                        membership_score=detection.structural_score,
                        reason=membership_reason(member, detection),
                    )
                )
            else:
                existing_member.membership_score = detection.structural_score
                existing_member.reason = membership_reason(member, detection)
        persisted.append(cluster)
    await session.flush()
    return persisted


async def compute_graph_for_transaction(
    session: AsyncSession,
    transaction_public_id: str,
    *,
    persist: bool = True,
) -> GraphAssessment:
    row = (
        await session.execute(
            transaction_history_query().where(Transaction.public_id == transaction_public_id)
        )
    ).one()
    current = row_to_graph_transaction(row)
    state = await PostgreSQLGraphProvider(session).state_for(current)
    assessment = GraphEngine().assess(current, state)
    validate_graph_assessment(assessment, current)
    if persist:
        await _persist_assessment(session, row[0], assessment)
        await session.commit()
    return assessment


async def backfill_graph(
    session: AsyncSession,
    *,
    limit: int | None = None,
) -> OfflineGraphResult:
    statement = transaction_history_query().order_by(Transaction.event_time, Transaction.public_id)
    if limit is not None:
        statement = statement.limit(limit)
    rows = list((await session.execute(statement)).all())
    transactions = [row_to_graph_transaction(row) for row in rows]
    result = await build_offline_graph(transactions)
    rows_by_public_id = {row[0].public_id: row[0] for row in rows}
    for assessment in result.assessments:
        await _persist_assessment(
            session,
            rows_by_public_id[assessment.transaction_public_id],
            assessment,
        )
    await persist_clusters(session, result.clusters)
    await session.commit()
    return result


def graph_schema_artifact() -> dict[str, object]:
    return {
        "graph_version": GRAPH_VERSION,
        "description": "Point-in-time heterogeneous identity graph assessment.",
        "metrics": [metric.as_dict() for metric in GRAPH_METRICS],
        "signals": list(SIGNAL_DEFINITIONS),
    }
