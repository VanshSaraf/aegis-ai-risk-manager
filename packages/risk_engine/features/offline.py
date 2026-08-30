from collections import Counter
from itertools import groupby

from apps.api.app.schemas.contracts import FeatureVector
from packages.risk_engine.features.domain import FeatureTransaction, TrainingExample
from packages.risk_engine.features.engine import FeatureEngine
from packages.risk_engine.features.history import InMemoryHistoryProvider
from packages.risk_engine.features.validation import validate_feature_vector
from packages.synthetic.domain import GeneratedEvent, SyntheticDataset


def generated_event_to_feature_transaction(event: GeneratedEvent) -> FeatureTransaction:
    facts = event.facts
    return FeatureTransaction(
        transaction_public_id=facts.event_id,
        customer_id=facts.customer_ref,
        merchant_id=facts.merchant_ref,
        instrument_id=facts.instrument_fingerprint,
        device_id=facts.device_fingerprint,
        ip_id=facts.ip_hash,
        address_id=facts.address_fingerprint,
        amount_paise=facts.amount_paise,
        currency=facts.currency,
        payment_method=facts.payment_method,
        event_time=facts.event_time,
        account_created_at=facts.account_created_at,
        status=facts.status,
        failure_code=facts.failure_code,
    )


async def build_offline_feature_vectors(
    transactions: list[FeatureTransaction],
) -> list[FeatureVector]:
    engine = FeatureEngine()
    history = InMemoryHistoryProvider()
    vectors: list[FeatureVector] = []
    ordered = sorted(
        transactions,
        key=lambda transaction: (transaction.event_time, transaction.transaction_public_id),
    )
    for _, same_time_iterator in groupby(ordered, key=lambda transaction: transaction.event_time):
        same_time = list(same_time_iterator)
        for transaction in same_time:
            vector = await engine.compute(transaction.scoring_context(), history)
            validate_feature_vector(vector, transaction.event_time)
            vectors.append(vector)
        history.observe_many(same_time)
    return vectors


async def build_training_examples(
    dataset: SyntheticDataset,
) -> tuple[list[FeatureVector], list[TrainingExample]]:
    events_by_id = {event.facts.event_id: event for event in dataset.events}
    vectors = await build_offline_feature_vectors(
        [generated_event_to_feature_transaction(event) for event in dataset.events]
    )
    examples = [
        TrainingExample(
            transaction_public_id=vector.transaction_public_id,
            features=vector.values,
            label=events_by_id[vector.transaction_public_id].truth.label.value,
            scenario=events_by_id[vector.transaction_public_id].truth.scenario_type.value,
            ring_id=events_by_id[vector.transaction_public_id].truth.ring_id,
        )
        for vector in vectors
    ]
    return vectors, examples


def summarize_vectors(vectors: list[FeatureVector]) -> dict[str, object]:
    return {
        "feature_version": FeatureEngine.feature_version,
        "vector_count": len(vectors),
        "feature_count": len(vectors[0].values) if vectors else 0,
        "vectors_with_history": sum(vector.max_source_event_time is not None for vector in vectors),
        "zero_counts": dict(
            Counter(
                name
                for vector in vectors
                for name, value in vector.values.items()
                if not isinstance(value, bool) and value == 0
            )
        ),
    }
