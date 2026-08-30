from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from apps.api.app.db.session import SessionFactory
from apps.api.app.models import (
    AbuseCluster,
    ClusterMember,
    EntityEdge,
    GraphAssessmentSnapshot,
    Transaction,
)
from apps.api.app.schemas.contracts import RawPaymentEvent
from apps.api.app.services.transactions import ingest_transaction
from apps.api.tests.factories import raw_event_payload
from packages.graph_engine import GraphEngine, InMemoryGraphState
from packages.graph_engine.postgres import PostgreSQLGraphProvider, row_to_graph_transaction
from packages.graph_engine.registry import GRAPH_METRIC_NAMES, GRAPH_VERSION
from packages.graph_engine.service import (
    backfill_graph,
    compute_graph_for_transaction,
    persist_clusters,
)
from packages.risk_engine.features.postgres import transaction_history_query

pytestmark = pytest.mark.integration


def event(event_id: str, minute: int, **overrides) -> RawPaymentEvent:
    event_time = datetime(2026, 8, 30, 10, tzinfo=UTC) + timedelta(minutes=minute)
    return RawPaymentEvent.model_validate(
        raw_event_payload(
            event_id,
            event_time=event_time.isoformat(),
            account_created_at=(event_time - timedelta(days=30)).isoformat(),
            **overrides,
        )
    )


async def test_postgresql_and_offline_graph_assessments_match(clean_database) -> None:
    async with SessionFactory() as session:
        await ingest_transaction(session, event("evt-graph-1", 0))
        await ingest_transaction(
            session,
            event(
                "evt-graph-2",
                5,
                customer_ref="customer-2",
                instrument_fingerprint="instrument-2",
            ),
        )
        await ingest_transaction(
            session,
            event(
                "evt-graph-3",
                10,
                customer_ref="customer-3",
                instrument_fingerprint="instrument-3",
            ),
        )
        rows = list(
            (
                await session.execute(transaction_history_query().order_by(Transaction.event_time))
            ).all()
        )
        transactions = [row_to_graph_transaction(row) for row in rows]
        current = transactions[-1]

        postgres_state = await PostgreSQLGraphProvider(session).state_for(current)
        postgres = GraphEngine().assess(current, postgres_state)
        offline = GraphEngine().assess(
            current,
            InMemoryGraphState(transactions[:-1]),
        )

        assert postgres.metrics == offline.metrics
        assert postgres.signals == offline.signals
        assert postgres.structural_score == offline.structural_score
        assert postgres.max_source_event_time == offline.max_source_event_time


async def test_future_entity_edges_cannot_change_old_graph_assessment(clean_database) -> None:
    async with SessionFactory() as session:
        await ingest_transaction(session, event("evt-edge-history", 0))
        old = await ingest_transaction(session, event("evt-edge-current", 5))
        before = await compute_graph_for_transaction(
            session,
            old.transaction_public_id,
            persist=False,
        )
        edge_count_before = sum((await session.scalars(select(EntityEdge.observation_count))).all())

        for index in range(4):
            await ingest_transaction(
                session,
                event(
                    f"evt-edge-future-{index}",
                    20 + index,
                    customer_ref=f"future-customer-{index}",
                    instrument_fingerprint=f"future-instrument-{index}",
                ),
            )
        edge_count_after = sum((await session.scalars(select(EntityEdge.observation_count))).all())
        after = await compute_graph_for_transaction(
            session,
            old.transaction_public_id,
            persist=False,
        )

        assert edge_count_after > edge_count_before
        assert before.metrics == after.metrics
        assert before.signals == after.signals
        assert before.structural_score == after.structural_score
        assert before.max_source_event_time == after.max_source_event_time


async def test_graph_snapshots_are_idempotent_and_version_safe(clean_database) -> None:
    async with SessionFactory() as session:
        normalized = await ingest_transaction(session, event("evt-graph-snapshot", 0))

        first = await compute_graph_for_transaction(session, normalized.transaction_public_id)
        second = await compute_graph_for_transaction(session, normalized.transaction_public_id)

        assert first.metrics == second.metrics
        assert await session.scalar(select(func.count()).select_from(GraphAssessmentSnapshot)) == 1
        transaction_row = await session.scalar(
            select(Transaction).where(Transaction.public_id == normalized.transaction_public_id)
        )
        assert transaction_row is not None
        session.add(
            GraphAssessmentSnapshot(
                transaction_id=transaction_row.id,
                graph_version="graph-v2-test",
                metrics={},
                signals=[],
                structural_score=0.0,
                component_fingerprints=[],
                candidate_cluster=False,
                computed_at=first.computed_at,
                max_source_event_time=None,
            )
        )
        await session.commit()

        assert await session.scalar(select(func.count()).select_from(GraphAssessmentSnapshot)) == 2
        versions = set(await session.scalars(select(GraphAssessmentSnapshot.graph_version)))
        assert versions == {GRAPH_VERSION, "graph-v2-test"}


async def test_postgresql_graph_backfill_preserves_same_timestamp_policy(
    clean_database,
) -> None:
    async with SessionFactory() as session:
        await ingest_transaction(session, event("evt-batch-1", 0))
        await ingest_transaction(
            session,
            event(
                "evt-batch-2",
                0,
                customer_ref="customer-2",
                instrument_fingerprint="instrument-2",
            ),
        )
        await ingest_transaction(
            session,
            event(
                "evt-batch-3",
                5,
                customer_ref="customer-3",
                instrument_fingerprint="instrument-3",
            ),
        )

        result = await backfill_graph(session)

        assert len(result.assessments) == 3
        assert all(tuple(item.metrics) == GRAPH_METRIC_NAMES for item in result.assessments)
        assert result.assessments[0].metrics["component_node_count"] == 0
        assert result.assessments[1].metrics["component_node_count"] == 0
        assert result.assessments[2].metrics["device_customer_degree"] == 2
        assert await session.scalar(select(func.count()).select_from(GraphAssessmentSnapshot)) == 3


async def test_cluster_rediscovery_deduplicates_and_expands_membership(clean_database) -> None:
    async with SessionFactory() as session:
        for index in range(12):
            await ingest_transaction(
                session,
                event(
                    f"evt-cluster-{index}",
                    index,
                    customer_ref=f"cluster-customer-{index % 4}",
                    instrument_fingerprint=f"cluster-instrument-{index % 5}",
                    device_fingerprint="cluster-device-core",
                    ip_hash="cluster-ip",
                    address_fingerprint=f"cluster-address-{index % 2}",
                ),
            )
        first = await backfill_graph(session)
        assert len(first.clusters) == 1
        cluster = await session.scalar(select(AbuseCluster))
        assert cluster is not None
        first_public_id = cluster.public_id
        first_member_count = await session.scalar(select(func.count()).select_from(ClusterMember))

        for index in range(2):
            await ingest_transaction(
                session,
                event(
                    f"evt-cluster-growth-{index}",
                    20 + index,
                    customer_ref=f"cluster-new-customer-{index}",
                    instrument_fingerprint=f"cluster-new-instrument-{index}",
                    device_fingerprint="cluster-device-core",
                    ip_hash="cluster-ip",
                    address_fingerprint="cluster-address-0",
                ),
            )
        second = await backfill_graph(session)
        assert len(second.clusters) == 1
        await persist_clusters(
            session,
            [replace(second.clusters[0], fingerprint="evolved-core-fingerprint")],
        )
        await session.commit()

        assert await session.scalar(select(func.count()).select_from(AbuseCluster)) == 1
        updated = await session.scalar(select(AbuseCluster))
        assert updated is not None
        assert updated.public_id == first_public_id
        assert (
            await session.scalar(select(func.count()).select_from(ClusterMember))
            > first_member_count
        )
        assert (
            "ring"
            not in json_text((await session.scalars(select(ClusterMember.reason))).all()).lower()
        )


def json_text(values) -> str:
    import json

    return json.dumps(values, sort_keys=True)
