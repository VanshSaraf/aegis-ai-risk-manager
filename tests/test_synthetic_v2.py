import hashlib
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import pytest

from apps.api.app.core.enums import GroundTruthLabel, ScenarioType, TransactionStatus
from packages.synthetic.config import load_generation_config
from packages.synthetic.generator import generate_dataset
from packages.synthetic.v2_validation import validate_hardened_v2


def _canonical_digest(dataset) -> str:
    payload = "\n".join(
        json.dumps(event.canonical(), sort_keys=True, separators=(",", ":"))
        for event in dataset.events
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.fixture(scope="module")
def v2_config():
    config = load_generation_config(Path("configs/scenarios/hardened-v2.yaml"))
    return config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"transaction_count": 5_000})}
    )


@pytest.fixture(scope="module")
def v2_dataset(v2_config):
    return generate_dataset(v2_config)


def test_synthetic_v1_canonical_world_is_preserved() -> None:
    config = load_generation_config()
    config = config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"transaction_count": 250})}
    )
    dataset = generate_dataset(config)
    assert dataset.generator_version == "synthetic-v1"
    assert _canonical_digest(dataset) == (
        "6ef13a5a429c020676915147a2c177cf103adadbfb7add0336b5763057b27e01"
    )


def test_synthetic_v2_is_distinct_and_deterministic(v2_config, v2_dataset) -> None:
    repeated = generate_dataset(v2_config)
    assert v2_dataset.generator_version == "synthetic-v2"
    assert v2_dataset.generator_version != load_generation_config().generator_version
    assert _canonical_digest(v2_dataset) == _canonical_digest(repeated)
    assert [event.truth.ring_id for event in v2_dataset.events] == [
        event.truth.ring_id for event in repeated.events
    ]


def test_v2_legitimate_high_velocity_and_retry_bursts_exist(v2_dataset) -> None:
    legitimate = [
        event for event in v2_dataset.events if event.truth.label == GroundTruthLabel.LEGITIMATE
    ]
    by_ip: dict[str, list] = defaultdict(list)
    by_customer: dict[str, list] = defaultdict(list)
    for event in legitimate:
        by_ip[event.facts.ip_hash].append(event)
        by_customer[event.facts.customer_ref].append(event)
    assert any(
        len(
            [
                other
                for other in events
                if event.facts.event_time
                <= other.facts.event_time
                <= event.facts.event_time + timedelta(minutes=10)
            ]
        )
        >= 6
        for events in by_ip.values()
        for event in events
    )
    assert any(
        sum(
            other.facts.status == TransactionStatus.FAILED
            and event.facts.event_time
            <= other.facts.event_time
            <= event.facts.event_time + timedelta(minutes=10)
            for other in events
        )
        >= 2
        for events in by_customer.values()
        for event in events
    )


def test_v2_legitimate_shared_devices_and_instruments_exist(v2_dataset) -> None:
    customers_by_device: dict[str, set[str]] = defaultdict(set)
    customers_by_instrument: dict[str, set[str]] = defaultdict(set)
    for event in v2_dataset.events:
        if event.truth.label != GroundTruthLabel.LEGITIMATE:
            continue
        customers_by_device[event.facts.device_fingerprint].add(event.facts.customer_ref)
        customers_by_instrument[event.facts.instrument_fingerprint].add(event.facts.customer_ref)
    assert max(map(len, customers_by_device.values())) >= 2
    assert max(map(len, customers_by_instrument.values())) >= 2


def test_v2_abuse_includes_slower_and_moderate_failure_rings(v2_dataset) -> None:
    rings: dict[str, list] = defaultdict(list)
    for event in v2_dataset.events:
        if event.truth.ring_id:
            rings[event.truth.ring_id].append(event)
    for scenario in (
        ScenarioType.CARD_TESTING,
        ScenarioType.ACCOUNT_FARM,
        ScenarioType.IDENTITY_ROTATION,
        ScenarioType.COLLUSIVE_RING,
    ):
        scenario_rings = [
            events for events in rings.values() if events[0].truth.scenario_type == scenario
        ]
        assert any(
            max(event.facts.event_time for event in events)
            - min(event.facts.event_time for event in events)
            >= timedelta(hours=2)
            for events in scenario_rings
        )
        assert any(
            0
            < sum(event.facts.status == TransactionStatus.FAILED for event in events) / len(events)
            <= 0.30
            for events in scenario_rings
        )


def test_v2_each_abuse_subtype_has_topology_variation_and_many_rings(v2_dataset) -> None:
    rings: dict[str, list] = defaultdict(list)
    for event in v2_dataset.events:
        if event.truth.ring_id:
            rings[event.truth.ring_id].append(event)
    counts = Counter(events[0].truth.scenario_type for events in rings.values())
    for scenario in (
        ScenarioType.CARD_TESTING,
        ScenarioType.ACCOUNT_FARM,
        ScenarioType.IDENTITY_ROTATION,
        ScenarioType.COLLUSIVE_RING,
    ):
        assert counts[scenario] >= 3
        signatures = {
            (
                len({event.facts.customer_ref for event in events}),
                len({event.facts.device_fingerprint for event in events}),
                len({event.facts.instrument_fingerprint for event in events}),
                len({event.facts.ip_hash for event in events}),
                len({event.facts.address_fingerprint for event in events}),
                int(
                    (
                        max(event.facts.event_time for event in events)
                        - min(event.facts.event_time for event in events)
                    ).total_seconds()
                    // 60
                ),
            )
            for events in rings.values()
            if events[0].truth.scenario_type == scenario
        }
        assert len(signatures) >= 3


def test_v2_truth_is_isolated_and_ring_ids_are_stable(v2_dataset) -> None:
    raw_keys = set(v2_dataset.events[0].facts.model_dump())
    assert not {"ground_truth_label", "ground_truth_scenario", "ring_id", "persona"} & raw_keys
    abuse = [event for event in v2_dataset.events if event.truth.ring_id]
    assert all(event.truth.label == GroundTruthLabel.COORDINATED_ABUSE for event in abuse)
    assert len({event.truth.ring_id for event in abuse}) >= 12


def test_v2_hardening_validator_passes_development_fixture(v2_dataset) -> None:
    report = validate_hardened_v2(v2_dataset)
    assert report["passed"] is True
