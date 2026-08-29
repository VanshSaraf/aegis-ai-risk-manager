from collections import defaultdict
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.api.app.core.enums import GroundTruthLabel, ScenarioType, TransactionStatus
from packages.synthetic import (
    build_manifest,
    generate_dataset,
    load_generation_config,
    validate_dataset,
)
from packages.synthetic.domain import LegitimatePersona, SyntheticGroundTruth


@pytest.fixture
def generation_config():
    config = load_generation_config()
    return config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"transaction_count": 250})}
    )


def test_same_seed_and_config_are_semantically_deterministic(generation_config) -> None:
    first = generate_dataset(generation_config)
    second = generate_dataset(generation_config)

    assert [event.canonical() for event in first.events] == [
        event.canonical() for event in second.events
    ]


def test_different_seed_materially_changes_world(generation_config) -> None:
    other = generation_config.model_copy(
        update={
            "dataset": generation_config.dataset.model_copy(
                update={"seed": generation_config.dataset.seed + 1}
            )
        }
    )
    first = generate_dataset(generation_config)
    second = generate_dataset(other)

    assert [event.canonical() for event in first.events[:20]] != [
        event.canonical() for event in second.events[:20]
    ]


def test_event_clock_is_utc_ordered_and_bounded(generation_config) -> None:
    dataset = generate_dataset(generation_config)
    timestamps = [event.facts.event_time for event in dataset.events]

    assert timestamps == sorted(timestamps)
    assert all(timestamp.utcoffset() == timedelta(0) for timestamp in timestamps)
    assert min(timestamps) >= generation_config.dataset.start_time
    assert max(timestamps) <= generation_config.dataset.start_time + timedelta(
        days=generation_config.dataset.simulation_days
    )


def test_all_legitimate_personas_create_false_positive_pressure(generation_config) -> None:
    events = [
        event
        for event in generate_dataset(generation_config).events
        if event.truth.label == GroundTruthLabel.LEGITIMATE
    ]
    assert {event.truth.persona for event in events} == set(LegitimatePersona)

    customers_by_ip: dict[str, set[str]] = defaultdict(set)
    customers_by_address: dict[str, set[str]] = defaultdict(set)
    for event in events:
        customers_by_ip[event.facts.ip_hash].add(event.facts.customer_ref)
        customers_by_address[event.facts.address_fingerprint].add(event.facts.customer_ref)
    assert any(len(customers) >= 2 for customers in customers_by_ip.values())
    assert any(len(customers) >= 2 for customers in customers_by_address.values())
    assert any(
        event.truth.persona == LegitimatePersona.TRAVELLER
        and event.facts.ip_region != event.facts.home_region
        for event in events
    )


@pytest.mark.parametrize(
    "scenario",
    [
        ScenarioType.CARD_TESTING,
        ScenarioType.ACCOUNT_FARM,
        ScenarioType.IDENTITY_ROTATION,
        ScenarioType.COLLUSIVE_RING,
    ],
)
def test_abuse_scenarios_have_rings_and_infrastructure_reuse(generation_config, scenario) -> None:
    isolated = generation_config.model_copy(
        update={"dataset": generation_config.dataset.model_copy(update={"transaction_count": 80})}
    )
    events = generate_dataset(isolated, scenario).events
    customers = {event.facts.customer_ref for event in events}
    infrastructure = {(event.facts.device_fingerprint, event.facts.ip_hash) for event in events}

    assert all(event.truth.label == GroundTruthLabel.COORDINATED_ABUSE for event in events)
    assert all(event.truth.scenario_type == scenario for event in events)
    assert all(event.truth.ring_id for event in events)
    assert len(infrastructure) < len(customers)
    assert any(event.facts.status == TransactionStatus.FAILED for event in events)


def test_card_testing_concentrates_many_instruments(generation_config) -> None:
    events = generate_dataset(generation_config, ScenarioType.CARD_TESTING).events
    assert len({event.facts.instrument_fingerprint for event in events}) > 2 * len(
        {event.facts.device_fingerprint for event in events}
    )


def test_account_farm_has_many_new_accounts_on_shared_devices(generation_config) -> None:
    events = generate_dataset(generation_config, ScenarioType.ACCOUNT_FARM).events
    new_accounts = {
        event.facts.customer_ref
        for event in events
        if event.facts.event_time - event.facts.account_created_at <= timedelta(days=30)
    }
    assert len(new_accounts) >= 5
    assert len({event.facts.customer_ref for event in events}) > len(
        {event.facts.device_fingerprint for event in events}
    )


def test_identity_rotation_keeps_infrastructure_while_identities_rotate(
    generation_config,
) -> None:
    events = generate_dataset(generation_config, ScenarioType.IDENTITY_ROTATION).events
    infrastructure = {(event.facts.device_fingerprint, event.facts.ip_hash) for event in events}
    identities = {
        (event.facts.customer_ref, event.facts.instrument_fingerprint) for event in events
    }
    assert len(identities) > len(infrastructure)


def test_collusive_ring_is_partial_not_fully_connected(generation_config) -> None:
    events = generate_dataset(generation_config, ScenarioType.COLLUSIVE_RING).events
    customers = {event.facts.customer_ref for event in events}
    instruments = {event.facts.instrument_fingerprint for event in events}
    observed_links = {
        (event.facts.customer_ref, event.facts.instrument_fingerprint) for event in events
    }
    assert len(customers) >= 5
    assert len(instruments) >= 5
    assert len(observed_links) < len(customers) * len(instruments)


def test_ground_truth_is_not_part_of_raw_or_scoring_facts(generation_config) -> None:
    event = generate_dataset(generation_config).events[0]
    raw_keys = event.facts.model_dump().keys()

    assert not {
        "ground_truth_label",
        "ground_truth_scenario",
        "ground_truth_ring_id",
        "persona",
    }.intersection(raw_keys)


def test_validator_passes_default_world_and_catches_bad_truth(generation_config) -> None:
    dataset = generate_dataset(generation_config)
    manifest = build_manifest(dataset, generation_config)
    assert validate_dataset(dataset, manifest, generation_config).status == "PASS"

    first_legitimate = next(
        index
        for index, event in enumerate(dataset.events)
        if event.truth.label == GroundTruthLabel.LEGITIMATE
    )
    bad_event = replace(
        dataset.events[first_legitimate],
        truth=SyntheticGroundTruth(
            label=GroundTruthLabel.LEGITIMATE,
            scenario_type=ScenarioType.NORMAL_TRAFFIC,
            ring_id="ring_invalid",
            persona=LegitimatePersona.STANDARD_RETAIL,
        ),
    )
    bad_events = list(dataset.events)
    bad_events[first_legitimate] = bad_event
    bad_dataset = replace(dataset, events=tuple(bad_events))
    report = validate_dataset(bad_dataset, manifest, generation_config)

    assert report.status == "FAIL"
    assert "legitimate_ring_id" in {issue.code for issue in report.issues}


def test_validator_rejects_collapsed_abuse_ring_diversity(generation_config) -> None:
    config = generation_config.model_copy(
        update={"dataset": generation_config.dataset.model_copy(update={"transaction_count": 120})}
    )
    scenario = ScenarioType.CARD_TESTING
    dataset = generate_dataset(config, scenario)
    collapsed_events = tuple(
        replace(
            event,
            truth=replace(event.truth, ring_id="ring_collapsed"),
        )
        for event in dataset.events
    )
    collapsed = replace(dataset, events=collapsed_events)
    manifest = build_manifest(collapsed, config)

    report = validate_dataset(collapsed, manifest, config, scenario)

    assert report.status == "FAIL"
    assert "insufficient_ring_diversity" in {issue.code for issue in report.issues}
