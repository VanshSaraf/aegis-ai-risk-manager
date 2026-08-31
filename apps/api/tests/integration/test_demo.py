from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from apps.api.app.models import (
    GraphAssessmentSnapshot,
    PolicyDecision,
    RawEvent,
    RiskPrediction,
    Transaction,
)

pytestmark = pytest.mark.integration


async def test_demo_step_uses_real_pipeline_is_truth_free_and_replay_safe(
    client, monkeypatch
) -> None:
    from apps.api.app.api import routes
    from apps.api.app.db.session import SessionFactory
    from apps.api.app.services.demo import DEMO_SESSIONS

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(demo_mode=True))
    await DEMO_SESSIONS.clear()
    started = await client.post("/api/v1/demo/sessions", json={"scenario": "IDENTITY_ROTATION"})
    assert started.status_code == 200
    session_body = started.json()
    assert session_body["session_id"].startswith("demo_")
    assert session_body["baseline_transactions"] == 12

    first = await client.post(
        f"/api/v1/demo/sessions/{session_body['session_id']}/step",
        json={"expected_step": 0},
    )
    replay = await client.post(
        f"/api/v1/demo/sessions/{session_body['session_id']}/step",
        json={"expected_step": 0},
    )
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    transaction_id = first.json()["transaction"]["public_id"]

    async with SessionFactory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.public_id == transaction_id)
        )
        assert transaction is not None
        assert transaction.scenario_run_id is None
        assert transaction.ground_truth_label is None
        assert transaction.ground_truth_scenario is None
        assert transaction.ground_truth_ring_id is None
        assert await session.scalar(select(func.count()).select_from(RawEvent)) == 13
        assert await session.scalar(select(func.count()).select_from(RiskPrediction)) == 13
        assert await session.scalar(select(func.count()).select_from(PolicyDecision)) == 13
        assert await session.scalar(select(func.count()).select_from(GraphAssessmentSnapshot)) == 13

    report = await client.get(f"/api/v1/transactions/{transaction_id}/investigation")
    assert report.status_code == 200
    serialized = str({"step": first.json(), "investigation": report.json()}).lower()
    for forbidden in (
        "ground_truth",
        "ring_id",
        "persona",
        "dataset_split",
        "failure_code",
        "fraud_probability",
    ):
        assert forbidden not in serialized
