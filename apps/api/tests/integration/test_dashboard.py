from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from apps.api.app.db.session import SessionFactory
from apps.api.app.models import PolicyDecision
from apps.api.tests.factories import raw_event_payload


async def test_dashboard_summary_and_transactions_are_truth_free(client) -> None:
    created = await client.post(
        "/api/v1/transactions", json=raw_event_payload("evt_dashboard_assessed")
    )
    transaction_id = created.json()["transaction_public_id"]
    assert (await client.post(f"/api/v1/transactions/{transaction_id}/assess")).status_code == 200
    assert (
        await client.post(
            "/api/v1/transactions",
            json=raw_event_payload(
                "evt_dashboard_pending",
                event_time=datetime(2026, 8, 30, 10, 31, tzinfo=UTC).isoformat(),
                customer_ref="dashboard_pending_customer",
            ),
        )
    ).status_code == 201

    summary_response = await client.get("/api/v1/dashboard/summary")
    transactions_response = await client.get("/api/v1/dashboard/transactions?limit=10")
    assert summary_response.status_code == transactions_response.status_code == 200
    summary = summary_response.json()
    items = transactions_response.json()["items"]
    assert summary["transaction_count"] == 2
    assert summary["assessed_count"] == 1
    assert len(items) == 2
    assert items[0]["assessed"] is False
    assert items[0]["action"] is None
    assessed = next(item for item in items if item["assessed"])
    async with SessionFactory() as session:
        persisted_decision = await session.scalar(
            select(PolicyDecision).where(PolicyDecision.policy_version == "risk-policy-v2")
        )
    assert persisted_decision is not None
    assert assessed["severity"] == persisted_decision.decision_reason["severity"]
    filtered = await client.get(
        "/api/v1/dashboard/transactions",
        params={"action": assessed["action"], "limit": 10},
    )
    assert filtered.status_code == 200
    assert [item["transaction_id"] for item in filtered.json()["items"]] == [transaction_id]
    serialized = str({"summary": summary, "items": items}).lower()
    for forbidden in (
        "ground_truth",
        "ring_id",
        "scenario",
        "persona",
        "dataset_split",
        "failure_code",
        "fraud_probability",
    ):
        assert forbidden not in serialized


async def test_transaction_graph_is_bounded_truth_free_and_point_in_time(client) -> None:
    current_time = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
    prior = raw_event_payload(
        "evt_graph_ui_prior",
        event_time=(current_time - timedelta(minutes=5)).isoformat(),
        customer_ref="graph_ui_prior_customer",
        device_fingerprint="graph_ui_shared_device",
    )
    current = raw_event_payload(
        "evt_graph_ui_current",
        event_time=current_time.isoformat(),
        customer_ref="graph_ui_current_customer",
        instrument_fingerprint="graph_ui_current_instrument",
        device_fingerprint="graph_ui_shared_device",
    )
    assert (await client.post("/api/v1/transactions", json=prior)).status_code == 201
    created = await client.post("/api/v1/transactions", json=current)
    transaction_id = created.json()["transaction_public_id"]
    assert (await client.post(f"/api/v1/transactions/{transaction_id}/assess")).status_code == 200

    before_response = await client.get(f"/api/v1/transactions/{transaction_id}/graph")
    assert before_response.status_code == 200
    before = before_response.json()
    assert before["has_prior_relationships"] is True
    assert len(before["nodes"]) <= before["max_nodes"] == 40
    assert len(before["edges"]) <= before["max_edges"] == 60

    future = raw_event_payload(
        "evt_graph_ui_future",
        event_time=(current_time + timedelta(minutes=5)).isoformat(),
        customer_ref="graph_ui_future_customer",
        instrument_fingerprint="graph_ui_future_instrument",
        device_fingerprint="graph_ui_shared_device",
    )
    assert (await client.post("/api/v1/transactions", json=future)).status_code == 201
    after = (await client.get(f"/api/v1/transactions/{transaction_id}/graph")).json()
    assert before == after
    assert "graph_ui_future" not in str(after)
    serialized = str(after).lower()
    for forbidden in ("ground_truth", "ring_id", "scenario", "persona", "split"):
        assert forbidden not in serialized


async def test_transaction_graph_reports_missing_and_unassessed_states(client) -> None:
    missing = await client.get("/api/v1/transactions/txn_missing/graph")
    assert missing.status_code == 404

    created = await client.post(
        "/api/v1/transactions", json=raw_event_payload("evt_graph_ui_unassessed")
    )
    transaction_id = created.json()["transaction_public_id"]
    unassessed = await client.get(f"/api/v1/transactions/{transaction_id}/graph")
    assert unassessed.status_code == 409
