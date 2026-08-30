from sqlalchemy import func, select

from apps.api.app.db.session import SessionFactory
from apps.api.app.models import (
    AuditEvent,
    GraphAssessmentSnapshot,
    PolicyDecision,
    RiskPrediction,
    RiskSignal,
    TransactionFeature,
)
from apps.api.tests.factories import raw_event_payload
from packages.policy_engine.config import load_policy_config
from packages.policy_engine.service import assess_transaction


async def test_operational_assessment_is_idempotent_truth_free_and_audited(client) -> None:
    created = await client.post(
        "/api/v1/transactions", json=raw_event_payload("evt_policy_assessment")
    )
    assert created.status_code == 201
    transaction_id = created.json()["transaction_public_id"]

    first = await client.post(f"/api/v1/transactions/{transaction_id}/assess")
    second = await client.post(f"/api/v1/transactions/{transaction_id}/assess")
    assert first.status_code == second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["risk_prediction_id"] == second_body["risk_prediction_id"]
    assert first_body["policy_decision_id"] == second_body["policy_decision_id"]
    assert first_body["model"]["version"] == "risk-lgbm-v2"
    assert first_body["graph"]["version"] == "graph-v1"
    assert first_body["policy"]["version"] == "risk-policy-v2"
    assert "not a fraud probability" in first_body["model"]["semantics"]
    serialized = str(first_body).lower()
    for forbidden in ("ground_truth", "ring_id", "persona", "scenario", "fraud_probability"):
        assert forbidden not in serialized

    async with SessionFactory() as session:
        prediction = await session.scalar(select(RiskPrediction))
        decision = await session.scalar(select(PolicyDecision))
        assert prediction is not None and decision is not None
        assert prediction.ml_score == first_body["model"]["score"]
        assert prediction.graph_score == first_body["graph"]["structural_score"]
        assert prediction.fused_score is None
        assert prediction.top_features == []
        assert await session.scalar(select(func.count()).select_from(RiskPrediction)) == 1
        assert await session.scalar(select(func.count()).select_from(PolicyDecision)) == 1
        assert await session.scalar(select(func.count()).select_from(TransactionFeature)) == 1
        assert await session.scalar(select(func.count()).select_from(GraphAssessmentSnapshot)) == 1
        assert await session.scalar(select(func.count()).select_from(RiskSignal)) >= 1
        audit_types = set(await session.scalars(select(AuditEvent.event_type)))
        assert {"RISK_PREDICTION_CREATED", "POLICY_DECISION_CREATED"}.issubset(audit_types)
        audit_payloads = list(await session.scalars(select(AuditEvent.payload)))
        assert all("ground_truth" not in str(payload).lower() for payload in audit_payloads)


async def test_assessment_rejects_an_immutable_prediction_mismatch(client) -> None:
    created = await client.post(
        "/api/v1/transactions", json=raw_event_payload("evt_policy_conflict")
    )
    transaction_id = created.json()["transaction_public_id"]
    assessed = await client.post(f"/api/v1/transactions/{transaction_id}/assess")
    assert assessed.status_code == 200

    async with SessionFactory() as session:
        prediction = await session.scalar(select(RiskPrediction))
        assert prediction is not None
        prediction.ml_score = min(prediction.ml_score + 0.1, 1.0)
        await session.commit()

    conflict = await client.post(f"/api/v1/transactions/{transaction_id}/assess")
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "immutable assessment conflict"


async def test_policy_v1_and_v2_can_coexist_and_remain_idempotent(client) -> None:
    created = await client.post(
        "/api/v1/transactions", json=raw_event_payload("evt_policy_version_coexistence")
    )
    transaction_id = created.json()["transaction_public_id"]
    assessed = await client.post(f"/api/v1/transactions/{transaction_id}/assess")
    assert assessed.status_code == 200

    policy_v1 = load_policy_config(version="risk-policy-v1")
    async with SessionFactory() as session:
        first_v1 = await assess_transaction(session, transaction_id, policy=policy_v1)
    async with SessionFactory() as session:
        second_v1 = await assess_transaction(session, transaction_id, policy=policy_v1)
        assert first_v1.policy_decision_id == second_v1.policy_decision_id
        versions = set(await session.scalars(select(PolicyDecision.policy_version)))
        assert versions == {"risk-policy-v1", "risk-policy-v2"}
        assert await session.scalar(select(func.count()).select_from(RiskPrediction)) == 1
        assert await session.scalar(select(func.count()).select_from(PolicyDecision)) == 2
