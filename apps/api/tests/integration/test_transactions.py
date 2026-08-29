from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from apps.api.app.core.enums import GroundTruthLabel, ProcessingStatus, ScenarioType
from apps.api.app.db.session import SessionFactory
from apps.api.app.models import Customer, EntityEdge, RawEvent, Transaction
from apps.api.app.schemas.contracts import RawPaymentEvent
from apps.api.app.schemas.internal import TrustedSyntheticContext
from apps.api.app.services.transactions import NormalizationError, ingest_transaction
from apps.api.tests.factories import raw_event_payload

pytestmark = pytest.mark.integration


async def test_ingestion_preserves_raw_event_and_creates_graph(client) -> None:
    payload = raw_event_payload()
    response = await client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["transaction_public_id"].startswith("txn_")
    assert body["amount_paise"] == 189999
    assert "ground_truth_label" not in body

    async with SessionFactory() as session:
        raw = await session.scalar(select(RawEvent).where(RawEvent.event_id == "evt_001"))
        assert raw is not None
        assert raw.payload["instrument_fingerprint"] == "inst_fp_001"
        assert raw.processing_status == ProcessingStatus.PROCESSED
        assert await session.scalar(select(func.count()).select_from(EntityEdge)) == 5

    neighbors = await client.get(
        f"/api/v1/entities/CUSTOMER/{body['customer_public_id']}/neighbors"
    )
    assert neighbors.status_code == 200
    assert len(neighbors.json()["neighbors"]) == 4


async def test_repeat_entities_are_reused_and_edges_increment(client) -> None:
    first = await client.post("/api/v1/transactions", json=raw_event_payload("evt_001"))
    second = await client.post(
        "/api/v1/transactions",
        json=raw_event_payload("evt_002", event_time="2026-08-30T09:30:00Z"),
    )
    assert first.status_code == second.status_code == 201

    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(Customer)) == 1
        edges = (await session.scalars(select(EntityEdge))).all()
        assert len(edges) == 5
        assert {edge.observation_count for edge in edges} == {2}
        assert {edge.first_seen_at for edge in edges} == {datetime(2026, 8, 30, 9, 30, tzinfo=UTC)}
        assert {edge.last_seen_at for edge in edges} == {datetime(2026, 8, 30, 10, 30, tzinfo=UTC)}


async def test_transaction_list_and_detail(client) -> None:
    created = await client.post("/api/v1/transactions", json=raw_event_payload())
    public_id = created.json()["transaction_public_id"]

    detail = await client.get(f"/api/v1/transactions/{public_id}")
    listing = await client.get("/api/v1/transactions?limit=10&offset=0")

    assert detail.status_code == 200
    assert detail.json()["transaction_public_id"] == public_id
    assert listing.status_code == 200
    assert [item["transaction_public_id"] for item in listing.json()["items"]] == [public_id]


async def test_normalization_failure_keeps_raw_and_rolls_back_everything_else(
    clean_database,
) -> None:
    event = RawPaymentEvent.model_validate(raw_event_payload())
    context = TrustedSyntheticContext(
        scenario_run_public_id="run_missing",
        label=GroundTruthLabel.LEGITIMATE,
        scenario_type=ScenarioType.NORMAL_TRAFFIC,
        persona="STANDARD_RETAIL",
    )
    async with SessionFactory() as session:
        with pytest.raises(NormalizationError, match="Unknown scenario_run_id"):
            await ingest_transaction(session, event, synthetic_context=context)
        raw = await session.scalar(select(RawEvent).where(RawEvent.event_id == "evt_001"))
        assert raw is not None
        assert raw.processing_status == ProcessingStatus.FAILED
        assert "Unknown scenario_run_id" in (raw.processing_error or "")
        assert await session.scalar(select(func.count()).select_from(Transaction)) == 0
        assert await session.scalar(select(func.count()).select_from(Customer)) == 0
        assert await session.scalar(select(func.count()).select_from(EntityEdge)) == 0


async def test_duplicate_event_is_rejected_without_second_raw_record(client) -> None:
    first = await client.post("/api/v1/transactions", json=raw_event_payload())
    second = await client.post("/api/v1/transactions", json=raw_event_payload())

    assert first.status_code == 201
    assert second.status_code == 409
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(RawEvent)) == 1


async def test_public_ingestion_rejects_ground_truth_fields(client) -> None:
    response = await client.post(
        "/api/v1/transactions",
        json=raw_event_payload(ground_truth_label="COORDINATED_ABUSE"),
    )

    assert response.status_code == 422
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(RawEvent)) == 0
