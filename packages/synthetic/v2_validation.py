from collections import Counter, defaultdict, deque
from datetime import timedelta

from apps.api.app.core.enums import GroundTruthLabel, ScenarioType, TransactionStatus
from packages.synthetic.domain import GeneratedEvent, SyntheticDataset


def _maximum_window_count(events: list[GeneratedEvent], field: str) -> int:
    by_entity: dict[str, list[GeneratedEvent]] = defaultdict(list)
    for event in events:
        by_entity[str(getattr(event.facts, field))].append(event)
    maximum = 0
    for entity_events in by_entity.values():
        window: deque[GeneratedEvent] = deque()
        for event in sorted(entity_events, key=lambda item: item.facts.event_time):
            while window and event.facts.event_time - window[0].facts.event_time > timedelta(
                minutes=10
            ):
                window.popleft()
            window.append(event)
            maximum = max(maximum, len(window))
    return maximum


def _failure_burst_exists(events: list[GeneratedEvent]) -> bool:
    failed = [event for event in events if event.facts.status == TransactionStatus.FAILED]
    return _maximum_window_count(failed, "customer_ref") >= 2


def _topology_signature(events: list[GeneratedEvent]) -> tuple[int, ...]:
    return (
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


def validate_hardened_v2(dataset: SyntheticDataset) -> dict[str, object]:
    if dataset.generator_version != "synthetic-v2":
        raise ValueError("hardened validation requires synthetic-v2")
    legitimate = [
        event for event in dataset.events if event.truth.label == GroundTruthLabel.LEGITIMATE
    ]
    abuse = [
        event for event in dataset.events if event.truth.label == GroundTruthLabel.COORDINATED_ABUSE
    ]
    customers_by_device: dict[str, set[str]] = defaultdict(set)
    customers_by_instrument: dict[str, set[str]] = defaultdict(set)
    for event in legitimate:
        customers_by_device[event.facts.device_fingerprint].add(event.facts.customer_ref)
        customers_by_instrument[event.facts.instrument_fingerprint].add(event.facts.customer_ref)
    rings: dict[str, list[GeneratedEvent]] = defaultdict(list)
    for event in abuse:
        assert event.truth.ring_id is not None
        rings[event.truth.ring_id].append(event)
    rings_by_entity: dict[str, set[str]] = defaultdict(set)
    for ring_id, events in rings.items():
        for event in events:
            for entity in (
                event.facts.customer_ref,
                event.facts.device_fingerprint,
                event.facts.instrument_fingerprint,
                event.facts.ip_hash,
                event.facts.address_fingerprint,
            ):
                rings_by_entity[entity].add(ring_id)
    cross_ring_shared_entities = sum(
        len(entity_rings) > 1 for entity_rings in rings_by_entity.values()
    )
    scenario_checks: dict[str, dict[str, object]] = {}
    for scenario in (
        ScenarioType.CARD_TESTING,
        ScenarioType.ACCOUNT_FARM,
        ScenarioType.IDENTITY_ROTATION,
        ScenarioType.COLLUSIVE_RING,
    ):
        scenario_rings = [
            events for events in rings.values() if events[0].truth.scenario_type == scenario
        ]
        signatures = {_topology_signature(events) for events in scenario_rings}
        slow_rings = sum(
            max(event.facts.event_time for event in events)
            - min(event.facts.event_time for event in events)
            >= timedelta(hours=2)
            for events in scenario_rings
        )
        moderate_failure_rings = sum(
            0
            < sum(event.facts.status == TransactionStatus.FAILED for event in events) / len(events)
            <= 0.30
            for events in scenario_rings
        )
        scenario_checks[scenario.value] = {
            "ring_count": len(scenario_rings),
            "topology_signature_count": len(signatures),
            "slow_ring_count": slow_rings,
            "moderate_failure_ring_count": moderate_failure_rings,
            "passed": len(signatures) >= 3 and slow_rings > 0 and moderate_failure_rings > 0,
        }
    checks = {
        "legitimate_ip_10m_max": _maximum_window_count(legitimate, "ip_hash"),
        "legitimate_device_10m_max": _maximum_window_count(legitimate, "device_fingerprint"),
        "legitimate_failure_burst": _failure_burst_exists(legitimate),
        "legitimate_shared_device_max_customers": max(map(len, customers_by_device.values())),
        "legitimate_shared_instrument_max_customers": max(
            map(len, customers_by_instrument.values())
        ),
        "ring_count": len(rings),
        "cross_ring_shared_abuse_entity_count": cross_ring_shared_entities,
        "rings_by_scenario": dict(
            sorted(
                Counter(events[0].truth.scenario_type.value for events in rings.values()).items()
            )
        ),
        "scenario_checks": scenario_checks,
    }
    checks["passed"] = bool(
        checks["legitimate_ip_10m_max"] >= 6
        and checks["legitimate_device_10m_max"] >= 4
        and checks["legitimate_failure_burst"]
        and checks["legitimate_shared_device_max_customers"] >= 2
        and checks["legitimate_shared_instrument_max_customers"] >= 2
        and checks["cross_ring_shared_abuse_entity_count"] == 0
        and all(bool(value["passed"]) for value in scenario_checks.values())
    )
    return checks
