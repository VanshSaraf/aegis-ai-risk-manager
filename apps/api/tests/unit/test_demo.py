from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.core.enums import PolicyAction, RiskSeverity
from apps.api.app.schemas.contracts import NormalizedTransaction
from apps.api.app.services import demo as demo_service
from apps.api.app.services.demo import DemoSessionRegistry
from packages.synthetic.demo import (
    BASELINE_TRANSACTION_COUNT,
    IDENTITY_ROTATION_STEP_COUNT,
    build_identity_rotation_demo,
)


def test_demo_sequence_is_deterministic_and_contains_no_truth() -> None:
    base_time = datetime(2026, 8, 31, 12, tzinfo=UTC)
    first = build_identity_rotation_demo("fixed", base_time)
    second = build_identity_rotation_demo("fixed", base_time)

    assert first == second
    assert len(first.baseline) == BASELINE_TRANSACTION_COUNT == 12
    assert len(first.showcase) == IDENTITY_ROTATION_STEP_COUNT == 18
    assert len({event.customer_ref for event in first.showcase}) == 18
    assert len({event.instrument_fingerprint for event in first.showcase}) == 6
    assert len({event.device_fingerprint for event in first.showcase}) == 1
    assert len({event.address_fingerprint for event in first.showcase}) == 3
    assert len({event.customer_ref for event in first.baseline}) == 3
    for event in (*first.baseline, *first.showcase):
        keys = event.model_dump().keys()
        assert not {"ground_truth", "ring_id", "scenario", "persona", "dataset_split"} & keys


async def test_expected_step_replay_ingests_each_demo_event_at_most_once(monkeypatch) -> None:
    ingested_event_ids: list[str] = []

    async def fake_ingest(session, event):
        del session
        ingested_event_ids.append(event.event_id)
        now = event.event_time
        return NormalizedTransaction(
            transaction_public_id=f"txn_{event.event_id}",
            customer_public_id=f"cus_{event.customer_ref}",
            merchant_public_id="mer_demo",
            payment_instrument_public_id=f"card_{event.instrument_fingerprint}",
            device_public_id=f"dev_{event.device_fingerprint}",
            ip_address_public_id=f"ip_{event.ip_hash}",
            address_public_id=f"addr_{event.address_fingerprint}",
            amount_paise=event.amount_paise,
            currency=event.currency,
            payment_method=event.payment_method,
            event_time=now,
            status=event.status,
            failure_code=event.failure_code,
            received_at=now,
            processed_at=now,
            created_at=now,
        )

    async def fake_assess(session, transaction_public_id):
        del session, transaction_public_id
        return SimpleNamespace(
            assessment=SimpleNamespace(
                model_score=0.42,
                severity=RiskSeverity.MEDIUM,
                graph_signals=(),
                detected_cluster_id=None,
            ),
            decision=SimpleNamespace(action=PolicyAction.VERIFY),
        )

    monkeypatch.setattr(demo_service, "ingest_transaction", fake_ingest)
    monkeypatch.setattr(demo_service, "assess_transaction", fake_assess)
    registry = DemoSessionRegistry(max_sessions=2)
    started = await demo_service.create_demo_session(
        None,
        registry=registry,
        session_id_factory=lambda: "demo_fixed",
        clock=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    assert len(ingested_event_ids) == BASELINE_TRANSACTION_COUNT

    first = await demo_service.step_demo_session(None, started.session_id, 0, registry=registry)
    replay = await demo_service.step_demo_session(None, started.session_id, 0, registry=registry)
    assert replay == first
    assert len(ingested_event_ids) == BASELINE_TRANSACTION_COUNT + 1

    for expected_step in range(1, started.total_steps):
        await demo_service.step_demo_session(
            None, started.session_id, expected_step, registry=registry
        )
    completed = await demo_service.step_demo_session(
        None, started.session_id, started.total_steps, registry=registry
    )
    assert completed.complete is True
    assert completed.transaction is None
    assert len(ingested_event_ids) == BASELINE_TRANSACTION_COUNT + started.total_steps
    assert len(ingested_event_ids) == len(set(ingested_event_ids))


async def test_failed_assessment_retry_reuses_already_ingested_transaction(monkeypatch) -> None:
    ingestion_count = 0
    assessment_count = 0

    async def fake_ingest(session, event):
        nonlocal ingestion_count
        del session
        ingestion_count += 1
        now = event.event_time
        return NormalizedTransaction(
            transaction_public_id=f"txn_{event.event_id}",
            customer_public_id="cus_demo",
            merchant_public_id="mer_demo",
            payment_instrument_public_id="card_demo",
            device_public_id="dev_demo",
            ip_address_public_id="ip_demo",
            address_public_id="addr_demo",
            amount_paise=event.amount_paise,
            currency=event.currency,
            payment_method=event.payment_method,
            event_time=now,
            status=event.status,
            failure_code=event.failure_code,
            received_at=now,
            processed_at=now,
            created_at=now,
        )

    async def fake_assess(session, transaction_public_id):
        nonlocal assessment_count
        del session, transaction_public_id
        assessment_count += 1
        if assessment_count == BASELINE_TRANSACTION_COUNT + 1:
            raise RuntimeError("temporary assessment failure")
        return SimpleNamespace(
            assessment=SimpleNamespace(
                model_score=0.42,
                severity=RiskSeverity.MEDIUM,
                graph_signals=(),
                detected_cluster_id=None,
            ),
            decision=SimpleNamespace(action=PolicyAction.VERIFY),
        )

    monkeypatch.setattr(demo_service, "ingest_transaction", fake_ingest)
    monkeypatch.setattr(demo_service, "assess_transaction", fake_assess)
    registry = DemoSessionRegistry()
    started = await demo_service.create_demo_session(
        None,
        registry=registry,
        session_id_factory=lambda: "demo_retry",
        clock=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    with pytest.raises(RuntimeError, match="temporary assessment failure"):
        await demo_service.step_demo_session(None, started.session_id, 0, registry=registry)
    ingestions_after_failure = ingestion_count

    response = await demo_service.step_demo_session(None, started.session_id, 0, registry=registry)
    assert response.step == 1
    assert ingestion_count == ingestions_after_failure


async def test_demo_endpoint_is_hidden_when_demo_mode_is_disabled(monkeypatch) -> None:
    from apps.api.app.api import routes
    from apps.api.app.main import app

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(demo_mode=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/demo/sessions", json={"scenario": "IDENTITY_ROTATION"}
        )
    assert response.status_code == 404
