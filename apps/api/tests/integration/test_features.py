from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from apps.api.app.db.session import SessionFactory
from apps.api.app.models import FeatureVersion, Transaction, TransactionFeature
from apps.api.app.schemas.contracts import RawPaymentEvent
from apps.api.app.services.transactions import ingest_transaction
from apps.api.tests.factories import raw_event_payload
from packages.risk_engine.features import FeatureEngine, InMemoryHistoryProvider
from packages.risk_engine.features.postgres import (
    PostgreSQLHistoryProvider,
    row_to_feature_transaction,
    transaction_history_query,
)
from packages.risk_engine.features.registry import FEATURE_NAMES, FEATURE_VERSION
from packages.risk_engine.features.service import backfill_features, compute_for_transaction

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


async def test_postgresql_and_in_memory_feature_vectors_match(clean_database) -> None:
    async with SessionFactory() as session:
        await ingest_transaction(session, event("evt-feature-1", 0, amount_paise=10_000))
        await ingest_transaction(
            session,
            event(
                "evt-feature-2",
                5,
                amount_paise=20_000,
                status="FAILED",
                failure_code="DECLINED",
            ),
        )
        await ingest_transaction(session, event("evt-feature-3", 10, amount_paise=30_000))
        rows = list(
            (
                await session.execute(transaction_history_query().order_by(Transaction.event_time))
            ).all()
        )
        transactions = [row_to_feature_transaction(row) for row in rows]
        current = transactions[-1]

        postgres = await FeatureEngine().compute(
            current.scoring_context(), PostgreSQLHistoryProvider(session)
        )
        offline = await FeatureEngine().compute(
            current.scoring_context(),
            InMemoryHistoryProvider(transactions[:-1]),
        )

        assert postgres.values == offline.values
        assert postgres.max_source_event_time == offline.max_source_event_time
        assert postgres.values["customer_failed_txn_count_1h"] == 1
        assert postgres.values["customer_avg_amount_30d"] == 15_000


async def test_feature_snapshots_are_idempotent_and_version_safe(clean_database) -> None:
    async with SessionFactory() as session:
        normalized = await ingest_transaction(session, event("evt-snapshot", 0))

        first = await compute_for_transaction(session, normalized.transaction_public_id)
        second = await compute_for_transaction(session, normalized.transaction_public_id)

        assert first.values == second.values
        assert await session.scalar(select(func.count()).select_from(TransactionFeature)) == 1
        transaction_row = await session.scalar(
            select(Transaction).where(Transaction.public_id == normalized.transaction_public_id)
        )
        assert transaction_row is not None
        session.add(
            FeatureVersion(
                version="features-v2-test",
                description="Schema-version coexistence test only.",
                feature_names=[],
            )
        )
        await session.flush()
        session.add(
            TransactionFeature(
                transaction_id=transaction_row.id,
                feature_version="features-v2-test",
                features={},
                computed_at=first.computed_at,
                max_source_event_time=None,
            )
        )
        await session.commit()

        assert await session.scalar(select(func.count()).select_from(TransactionFeature)) == 2
        versions = set(await session.scalars(select(TransactionFeature.feature_version)))
        assert versions == {FEATURE_VERSION, "features-v2-test"}


async def test_future_profile_mutations_cannot_change_old_features(clean_database) -> None:
    async with SessionFactory() as session:
        await ingest_transaction(session, event("evt-profile-history", 0, amount_paise=10_000))
        old = await ingest_transaction(
            session, event("evt-profile-current", 5, amount_paise=20_000)
        )
        before = await compute_for_transaction(
            session,
            old.transaction_public_id,
            persist=False,
        )

        await ingest_transaction(
            session,
            event(
                "evt-profile-future",
                20,
                home_region="IN-DL",
                customer_segment="ENTERPRISE",
                merchant_region="IN-TN",
                merchant_category="TRAVEL",
                merchant_risk_baseline=0.95,
                device_fingerprint="device-future",
            ),
        )
        after = await compute_for_transaction(
            session,
            old.transaction_public_id,
            persist=False,
        )

        assert before.values == after.values
        assert before.max_source_event_time == after.max_source_event_time


async def test_postgresql_backfill_persists_valid_point_in_time_snapshots(
    clean_database,
) -> None:
    async with SessionFactory() as session:
        await ingest_transaction(session, event("evt-backfill-1", 0))
        await ingest_transaction(session, event("evt-backfill-2", 0))
        await ingest_transaction(session, event("evt-backfill-3", 5))

        vectors = await backfill_features(session)

        assert len(vectors) == 3
        assert all(tuple(vector.values) == FEATURE_NAMES for vector in vectors)
        assert vectors[0].values["device_txn_count_10m"] == 0
        assert vectors[1].values["device_txn_count_10m"] == 0
        assert vectors[2].values["device_txn_count_10m"] == 2
        assert await session.scalar(select(func.count()).select_from(TransactionFeature)) == 3
        assert await session.get(FeatureVersion, FEATURE_VERSION) is not None
