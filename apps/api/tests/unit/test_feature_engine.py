import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.api.app.core.enums import TransactionStatus
from packages.risk_engine.features import (
    FEATURE_NAMES,
    FeatureEngine,
    FeatureTransaction,
    InMemoryHistoryProvider,
    build_offline_feature_vectors,
    generated_event_to_feature_transaction,
    validate_feature_vector,
)
from packages.risk_engine.features.service import feature_schema_artifact
from packages.synthetic import generate_dataset, load_generation_config


def transaction(
    public_id: str,
    minute: float,
    **overrides,
) -> FeatureTransaction:
    event_time = datetime(2026, 1, 2, tzinfo=UTC) + timedelta(minutes=minute)
    values = {
        "transaction_public_id": public_id,
        "customer_id": "customer-1",
        "merchant_id": "merchant-1",
        "instrument_id": "instrument-1",
        "device_id": "device-1",
        "ip_id": "ip-1",
        "address_id": "address-1",
        "amount_paise": 10_000,
        "currency": "INR",
        "payment_method": "CARD",
        "event_time": event_time,
        "account_created_at": event_time - timedelta(days=30),
        "status": TransactionStatus.AUTHORIZED,
        "failure_code": None,
    }
    values.update(overrides)
    return FeatureTransaction(**values)


async def values_for(
    current: FeatureTransaction,
    history: list[FeatureTransaction],
) -> dict[str, float | int | bool]:
    vector = await FeatureEngine().compute(
        current.scoring_context(), InMemoryHistoryProvider(history)
    )
    validate_feature_vector(vector, current.event_time)
    return vector.values


async def test_current_transaction_does_not_count_itself() -> None:
    current = transaction("current", 10)
    values = await values_for(current, [current])

    assert values["device_txn_count_10m"] == 0
    assert values["customer_txn_count_30d"] == 0
    assert values["is_new_device_for_customer"] is True


async def test_future_event_cannot_change_past_vector() -> None:
    previous = transaction("previous", 0)
    current = transaction("current", 10)
    future = transaction("future", 20, status=TransactionStatus.FAILED, failure_code="DECLINED")

    before = await values_for(current, [previous])
    after = await values_for(current, [previous, future])

    assert before == after


async def test_current_outcome_and_failure_code_are_excluded() -> None:
    history = [transaction("previous", 0)]
    authorized = transaction("current-a", 10)
    failed = replace(
        authorized,
        status=TransactionStatus.FAILED,
        failure_code="DECLINED",
    )

    assert not hasattr(authorized.scoring_context(), "status")
    assert not hasattr(authorized.scoring_context(), "failure_code")
    assert await values_for(authorized, history) == await values_for(failed, history)


async def test_same_timestamp_transactions_have_no_mutual_history() -> None:
    first = transaction("same-a", 10, customer_id="customer-a")
    second = transaction("same-b", 10, customer_id="customer-b")

    vectors = await build_offline_feature_vectors([first, second])

    assert [vector.values["device_txn_count_10m"] for vector in vectors] == [0, 0]
    assert [vector.values["historical_customers_on_current_device"] for vector in vectors] == [
        0,
        0,
    ]


async def test_window_boundary_is_closed_on_left_and_open_on_right() -> None:
    current = transaction("current", 20)
    just_inside = transaction("inside", 10.0001)
    exact_boundary = transaction("boundary", 10)
    just_outside = transaction("outside", 9.9999)

    values = await values_for(current, [just_inside, exact_boundary, just_outside])

    assert values["device_txn_count_10m"] == 2


async def test_new_entity_flags_turn_off_after_prior_use() -> None:
    previous = transaction("previous", 0)
    current = transaction("current", 10)

    values = await values_for(current, [previous])

    assert values["is_new_device_for_customer"] is False
    assert values["is_new_instrument_for_customer"] is False
    assert values["is_new_ip_for_customer"] is False
    assert values["is_new_address_for_customer"] is False


async def test_only_historical_failures_affect_failure_features() -> None:
    failed = transaction(
        "failed",
        0,
        status=TransactionStatus.FAILED,
        failure_code="DECLINED",
    )
    current = transaction("current", 5)
    future_failure = replace(failed, transaction_public_id="future", event_time=current.event_time)

    values = await values_for(current, [failed, future_failure])

    assert values["device_failed_txn_count_10m"] == 1
    assert values["customer_failure_rate_30d"] == 1.0


async def test_customer_amount_history_has_finite_defaults_and_statistics() -> None:
    current = transaction("current", 20, amount_paise=30_000)
    no_history = await values_for(current, [])
    history = [
        transaction("first", 0, amount_paise=10_000),
        transaction("second", 10, amount_paise=20_000),
    ]
    with_history = await values_for(current, history)

    assert no_history["customer_avg_amount_30d"] == 0.0
    assert no_history["amount_zscore_customer"] == 0.0
    assert with_history["customer_avg_amount_30d"] == 15_000
    assert with_history["customer_amount_std_30d"] == 5_000
    assert with_history["amount_vs_customer_mean"] == 2.0
    assert with_history["amount_zscore_customer"] == 3.0


async def test_relationship_counts_are_raw_point_in_time_counts() -> None:
    history = [
        transaction("first", 0, customer_id="customer-a", instrument_id="instrument-a"),
        transaction("second", 1, customer_id="customer-b", instrument_id="instrument-b"),
        transaction("third", 2, customer_id="customer-c", device_id="device-other"),
    ]
    current = transaction("current", 10, customer_id="customer-new")

    values = await values_for(current, history)

    assert values["historical_customers_on_current_device"] == 2
    assert values["historical_instruments_on_current_device"] == 2
    assert values["historical_customers_on_current_ip"] == 3
    assert values["historical_devices_on_current_ip"] == 2
    assert values["historical_customers_on_current_address"] == 3


async def test_synthetic_feature_vectors_have_one_leakage_free_schema() -> None:
    config = load_generation_config()
    config = config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"transaction_count": 250})}
    )
    dataset = generate_dataset(config)

    vectors = await build_offline_feature_vectors(
        [generated_event_to_feature_transaction(event) for event in dataset.events]
    )

    assert len(vectors) == 250
    assert len(FEATURE_NAMES) == 52
    assert all(tuple(vector.values) == FEATURE_NAMES for vector in vectors)
    forbidden = ("ground_truth", "scenario", "ring", "persona", "status", "failure_code")
    assert not any(fragment in name for name in FEATURE_NAMES for fragment in forbidden)
    assert all(
        vector.max_source_event_time is None
        or vector.max_source_event_time
        < next(
            event.facts.event_time
            for event in dataset.events
            if event.facts.event_id == vector.transaction_public_id
        )
        for vector in vectors
    )


def test_registry_is_exactly_features_v1() -> None:
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES)) == 52


async def test_validator_rejects_ground_truth_and_non_finite_values() -> None:
    current = transaction("current", 10)
    vector = await FeatureEngine().compute(current.scoring_context(), InMemoryHistoryProvider())
    with_truth = vector.model_copy(update={"values": {**vector.values, "ground_truth_label": 1}})
    non_finite = vector.model_copy(update={"values": {**vector.values, "log_amount": float("inf")}})

    with pytest.raises(ValueError, match="schema mismatch"):
        validate_feature_vector(with_truth, current.event_time)
    with pytest.raises(ValueError, match="must be finite"):
        validate_feature_vector(non_finite, current.event_time)


def test_committed_schema_artifact_matches_registry() -> None:
    artifact_path = Path("ml/artifacts/features-v1/schema.json")

    assert json.loads(artifact_path.read_text(encoding="utf-8")) == feature_schema_artifact()
