import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.api.app.core.enums import GraphEntityType, ScenarioType
from packages.graph_engine import (
    GRAPH_METRIC_NAMES,
    GraphEngine,
    GraphEntityRef,
    GraphTransaction,
    InMemoryGraphState,
    build_offline_graph,
    build_synthetic_graph,
    validate_graph_assessment,
)
from packages.graph_engine.service import graph_schema_artifact
from packages.synthetic import generate_dataset, load_generation_config
from packages.synthetic.domain import LegitimatePersona


def transaction(public_id: str, minute: float, **overrides) -> GraphTransaction:
    values = {
        "transaction_public_id": public_id,
        "customer_id": "customer-1",
        "instrument_id": "instrument-1",
        "device_id": "device-1",
        "ip_id": "ip-1",
        "address_id": "address-1",
        "amount_paise": 10_000,
        "event_time": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute),
    }
    values.update(overrides)
    return GraphTransaction(**values)


def test_graph_entity_identity_is_typed() -> None:
    customer = GraphEntityRef(GraphEntityType.CUSTOMER, "same-id")
    device = GraphEntityRef(GraphEntityType.DEVICE, "same-id")

    assert customer != device
    assert customer.canonical() == "CUSTOMER:same-id"
    assert not hasattr(transaction("current", 0), "status")
    assert not hasattr(transaction("current", 0), "failure_code")


def test_edge_creation_and_temporal_updates() -> None:
    state = InMemoryGraphState()
    first = transaction("first", 0)
    second = transaction("second", 5)

    state.observe(first)
    state.observe(second)
    customer, instrument, device, _ip, _address = first.entities()

    assert state.has_edge(customer, device)
    assert state.has_edge(instrument, device)
    metadata = state.edges[(customer, device) if customer < device else (device, customer)]
    assert metadata.first_seen_at == first.event_time
    assert metadata.last_seen_at == second.event_time
    assert metadata.observation_count == 2


def test_first_transaction_has_no_self_leakage_and_all_edges_are_new() -> None:
    current = transaction("current", 0)
    assessment = GraphEngine().assess(current, InMemoryGraphState())

    assert assessment.metrics["device_customer_degree"] == 0
    assert assessment.metrics["component_node_count"] == 0
    assert all(
        assessment.metrics[name] is True
        for name in (
            "new_customer_device_edge",
            "new_customer_instrument_edge",
            "new_customer_ip_edge",
            "new_customer_address_edge",
            "new_instrument_device_edge",
        )
    )
    assert assessment.max_source_event_time is None


def test_component_metrics_use_allowed_multipartite_capacity() -> None:
    previous = transaction("previous", 0)
    current = transaction("current", 5)
    assessment = GraphEngine().assess(current, InMemoryGraphState([previous]))

    assert assessment.metrics["component_node_count"] == 5
    assert assessment.metrics["component_edge_count"] == 5
    assert assessment.metrics["component_multipartite_density"] == 1.0
    assert assessment.metrics["device_customer_degree"] == 1
    assert assessment.metrics["instrument_device_degree"] == 1


def test_current_transaction_detects_component_bridge_without_observing_it() -> None:
    first = transaction("first", 0)
    second = transaction(
        "second",
        1,
        customer_id="customer-2",
        instrument_id="instrument-2",
        device_id="device-2",
        ip_id="ip-2",
        address_id="address-2",
    )
    current = transaction(
        "bridge",
        5,
        device_id="device-2",
        instrument_id="instrument-new",
        ip_id="ip-new",
        address_id="address-new",
    )

    assessment = GraphEngine().assess(current, InMemoryGraphState([first, second]))

    assert assessment.metrics["preexisting_component_count"] == 2
    assert assessment.metrics["components_bridged_by_transaction"] == 1
    assert "MULTI_COMPONENT_BRIDGE" in {signal.code for signal in assessment.signals}


def test_two_hop_and_temporal_expansion_metrics() -> None:
    history = [
        transaction("first", 0, customer_id="customer-1", instrument_id="instrument-1"),
        transaction("second", 1, customer_id="customer-2", instrument_id="instrument-2"),
    ]
    current = transaction("current", 5, customer_id="customer-3", instrument_id="instrument-3")

    assessment = GraphEngine().assess(current, InMemoryGraphState(history))

    assert assessment.metrics["customer_two_hop_customer_count_via_device_or_ip"] == 2
    assert assessment.metrics["component_new_edges_10m"] == 10
    assert assessment.metrics["device_new_identities_10m"] == 4


async def test_same_timestamp_transactions_do_not_see_each_other() -> None:
    first = transaction("same-a", 1, customer_id="customer-a", instrument_id="instrument-a")
    second = transaction("same-b", 1, customer_id="customer-b", instrument_id="instrument-b")

    result = await build_offline_graph([first, second])

    assert [item.metrics["device_customer_degree"] for item in result.assessments] == [0, 0]
    assert [item.metrics["component_node_count"] for item in result.assessments] == [0, 0]


async def test_future_graph_activity_cannot_change_old_assessment() -> None:
    first = transaction("first", 0)
    current = transaction("current", 5)
    future = transaction(
        "future",
        10,
        customer_id="customer-future",
        instrument_id="instrument-future",
    )

    before = await build_offline_graph([first, current])
    after = await build_offline_graph([first, current, future])
    before_current = next(
        item for item in before.assessments if item.transaction_public_id == "current"
    )
    after_current = next(
        item for item in after.assessments if item.transaction_public_id == "current"
    )

    assert before_current.metrics == after_current.metrics
    assert before_current.signals == after_current.signals
    assert before_current.structural_score == after_current.structural_score


@pytest.mark.parametrize(
    "scenario",
    [
        ScenarioType.CARD_TESTING,
        ScenarioType.ACCOUNT_FARM,
        ScenarioType.IDENTITY_ROTATION,
        ScenarioType.COLLUSIVE_RING,
    ],
)
async def test_each_abuse_scenario_produces_structural_clusters(scenario) -> None:
    config = load_generation_config()
    config = config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"transaction_count": 80})}
    )
    dataset = generate_dataset(config, scenario)

    result = await build_synthetic_graph(dataset)

    assert result.clusters
    assert all(cluster.structural_score >= 0.45 for cluster in result.clusters)
    ground_truth_ring_ids = {event.truth.ring_id for event in dataset.events if event.truth.ring_id}
    assert not ground_truth_ring_ids.intersection(
        cluster.fingerprint for cluster in result.clusters
    )


@pytest.mark.parametrize("persona", list(LegitimatePersona))
async def test_legitimate_persona_does_not_create_structural_clusters(persona) -> None:
    config = load_generation_config()
    config = config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"transaction_count": 500})}
    )
    dataset = generate_dataset(config, ScenarioType.NORMAL_TRAFFIC)
    persona_dataset = replace(
        dataset,
        events=tuple(event for event in dataset.events if event.truth.persona == persona),
    )

    result = await build_synthetic_graph(persona_dataset)

    assert result.assessments
    assert result.clusters == []
    assert max(item.structural_score for item in result.assessments) < 0.45


async def test_ground_truth_changes_cannot_change_graph_assessments() -> None:
    config = load_generation_config()
    config = config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"transaction_count": 80})}
    )
    dataset = generate_dataset(config, ScenarioType.CARD_TESTING)
    changed = replace(
        dataset,
        events=tuple(
            replace(event, truth=replace(event.truth, ring_id="ring_unrelated"))
            for event in dataset.events
        ),
    )

    original = await build_synthetic_graph(dataset)
    mutated = await build_synthetic_graph(changed)

    assert [item.metrics for item in original.assessments] == [
        item.metrics for item in mutated.assessments
    ]
    assert [item.structural_score for item in original.assessments] == [
        item.structural_score for item in mutated.assessments
    ]


def test_graph_registry_artifact_and_integrity_validation() -> None:
    assert len(GRAPH_METRIC_NAMES) == len(set(GRAPH_METRIC_NAMES)) == 25
    artifact = json.loads(Path("ml/artifacts/graph-v1/schema.json").read_text(encoding="utf-8"))
    assert artifact == graph_schema_artifact()
    current = transaction("current", 5)
    assessment = GraphEngine().assess(current, InMemoryGraphState())
    validate_graph_assessment(assessment, current)
