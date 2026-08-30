from itertools import groupby

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import FeatureVersion, Transaction, TransactionFeature
from apps.api.app.schemas.contracts import FeatureVector
from packages.risk_engine.features.engine import FeatureEngine
from packages.risk_engine.features.history import InMemoryHistoryProvider
from packages.risk_engine.features.postgres import (
    PostgreSQLHistoryProvider,
    row_to_feature_transaction,
    transaction_history_query,
)
from packages.risk_engine.features.registry import FEATURE_NAMES, FEATURE_VERSION, FEATURES_V1
from packages.risk_engine.features.validation import validate_feature_vector


class FeatureSnapshotConflictError(ValueError):
    pass


async def ensure_feature_version(session: AsyncSession) -> FeatureVersion:
    existing = await session.get(FeatureVersion, FEATURE_VERSION)
    description = "Point-in-time transaction, customer, velocity, and relationship features."
    if existing is None:
        existing = FeatureVersion(
            version=FEATURE_VERSION,
            description=description,
            feature_names=list(FEATURE_NAMES),
        )
        session.add(existing)
        await session.flush()
    elif existing.feature_names != list(FEATURE_NAMES) or existing.description != description:
        raise FeatureSnapshotConflictError("features-v1 registry metadata does not match")
    return existing


async def _persist_snapshot(
    session: AsyncSession,
    transaction: Transaction,
    vector: FeatureVector,
) -> TransactionFeature:
    existing = await session.scalar(
        select(TransactionFeature).where(
            TransactionFeature.transaction_id == transaction.id,
            TransactionFeature.feature_version == vector.feature_version,
        )
    )
    if existing is not None:
        if (
            existing.features != vector.values
            or existing.max_source_event_time != vector.max_source_event_time
        ):
            raise FeatureSnapshotConflictError(
                f"immutable feature snapshot mismatch for {transaction.public_id}"
            )
        return existing
    snapshot = TransactionFeature(
        transaction_id=transaction.id,
        feature_version=vector.feature_version,
        features=vector.values,
        computed_at=vector.computed_at,
        max_source_event_time=vector.max_source_event_time,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def compute_for_transaction(
    session: AsyncSession,
    transaction_public_id: str,
    *,
    persist: bool = True,
) -> FeatureVector:
    row = (
        await session.execute(
            transaction_history_query().where(Transaction.public_id == transaction_public_id)
        )
    ).one()
    current = row_to_feature_transaction(row)
    vector = await FeatureEngine().compute(
        current.scoring_context(), PostgreSQLHistoryProvider(session)
    )
    validate_feature_vector(vector, current.event_time)
    if persist:
        await ensure_feature_version(session)
        await _persist_snapshot(session, row[0], vector)
        await session.commit()
    return vector


async def backfill_features(
    session: AsyncSession,
    *,
    limit: int | None = None,
) -> list[FeatureVector]:
    statement = transaction_history_query().order_by(Transaction.event_time, Transaction.public_id)
    if limit is not None:
        statement = statement.limit(limit)
    rows = list((await session.execute(statement)).all())
    await ensure_feature_version(session)
    engine = FeatureEngine()
    history = InMemoryHistoryProvider()
    vectors: list[FeatureVector] = []
    for _, same_time_rows_iterator in groupby(rows, key=lambda row: row[0].event_time):
        same_time_rows = list(same_time_rows_iterator)
        same_time_transactions = [row_to_feature_transaction(row) for row in same_time_rows]
        for row, transaction in zip(same_time_rows, same_time_transactions, strict=True):
            vector = await engine.compute(transaction.scoring_context(), history)
            validate_feature_vector(vector, transaction.event_time)
            await _persist_snapshot(session, row[0], vector)
            vectors.append(vector)
        history.observe_many(same_time_transactions)
    await session.commit()
    return vectors


def feature_schema_artifact() -> dict[str, object]:
    return {
        "feature_version": FEATURE_VERSION,
        "description": "Point-in-time predictive feature contract; no labels or outcomes.",
        "features": [spec.as_dict() for spec in FEATURES_V1],
    }
