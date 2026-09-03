from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from apps.api.app.db.session import SessionFactory
from apps.api.app.models import (
    AuditEvent,
    GraphAssessmentSnapshot,
    Merchant,
    PolicyDecision,
    RiskPrediction,
    RiskSignal,
    TransactionFeature,
)
from apps.api.tests.factories import raw_event_payload
from packages.investigator.evidence import EvidenceBuilder
from packages.investigator.service import InvestigatorService
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

    investigation = await client.get(f"/api/v1/transactions/{transaction_id}/investigation")
    assert investigation.status_code == 200
    investigation_body = investigation.json()
    assert investigation_body["generated_by"] == "DETERMINISTIC"
    assert investigation_body["llm_status"] == "DISABLED"
    assert investigation_body["policy"]["version"] == "risk-policy-v2"
    assert investigation_body["model"]["version"] == "risk-lgbm-v2"
    assert investigation_body["graph"]["version"] == "graph-v1"
    policy = load_policy_config()
    assert investigation_body["policy"]["verify_threshold"] == policy.verify_threshold
    assert investigation_body["policy"]["hold_threshold"] == policy.hold_threshold
    assert investigation_body["policy"]["strong_signal_codes"] == list(
        policy.graph_corroboration.strong_signal_codes
    )
    assert investigation_body["why_not_stronger"]
    assert investigation_body["provenance"]["feature_computed_at"]
    assert investigation_body["provenance"]["graph_computed_at"]
    assert investigation_body["provenance"]["prediction_created_at"]
    assert investigation_body["provenance"]["decision_created_at"]
    assert "not a fraud probability" in investigation_body["model"]["semantics"]
    serialized_investigation = str(investigation_body).lower()
    for forbidden in (
        "ground_truth",
        "ring_id",
        "persona",
        "scenario",
        "split",
        "failure_code",
        "fraud_probability",
    ):
        assert forbidden not in serialized_investigation


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


async def test_investigation_is_point_in_time_and_provider_failure_is_read_only(client) -> None:
    current_time = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    prior = raw_event_payload(
        "evt_investigation_prior",
        event_time=(current_time - timedelta(minutes=5)).isoformat(),
        customer_ref="investigation_prior_customer",
        instrument_fingerprint="investigation_prior_instrument",
    )
    current = raw_event_payload(
        "evt_investigation_current",
        event_time=current_time.isoformat(),
        customer_ref="investigation_current_customer",
        instrument_fingerprint="investigation_current_instrument",
        merchant_ref="investigation_mutable_merchant",
        merchant_category="CATEGORY_A",
    )
    assert (await client.post("/api/v1/transactions", json=prior)).status_code == 201
    created = await client.post("/api/v1/transactions", json=current)
    transaction_id = created.json()["transaction_public_id"]
    assert (await client.post(f"/api/v1/transactions/{transaction_id}/assess")).status_code == 200
    before = (await client.get(f"/api/v1/transactions/{transaction_id}/investigation")).json()
    async with SessionFactory() as session:
        bundle_before = await EvidenceBuilder().build(session, transaction_id)
    assert "merchant_category" not in bundle_before.transaction.model_dump()
    assert len(before["timeline"]) == 1
    timeline_time = datetime.fromisoformat(
        before["timeline"][0]["event_time"].replace("Z", "+00:00")
    )
    assert timeline_time < current_time

    future = raw_event_payload(
        "evt_investigation_future",
        event_time=(current_time + timedelta(minutes=5)).isoformat(),
        customer_ref="investigation_future_customer",
        instrument_fingerprint="investigation_future_instrument",
        merchant_ref="investigation_mutable_merchant",
        merchant_category="CATEGORY_B",
    )
    assert (await client.post("/api/v1/transactions", json=future)).status_code == 201
    after = (await client.get(f"/api/v1/transactions/{transaction_id}/investigation")).json()
    async with SessionFactory() as session:
        bundle_after = await EvidenceBuilder().build(session, transaction_id)
        merchant_category = await session.scalar(
            select(Merchant.category).where(Merchant.source_ref == "investigation_mutable_merchant")
        )
    assert merchant_category == "CATEGORY_B"
    assert bundle_before == bundle_after
    assert "merchant_category" not in bundle_after.transaction.model_dump()
    assert "CATEGORY_B" not in str(bundle_after.model_dump())
    assert "CATEGORY_B" not in str(after)
    before.pop("generated_at")
    after.pop("generated_at")
    assert before == after

    class ThrowingProvider:
        async def generate(self, evidence):
            del evidence
            raise RuntimeError("simulated provider outage")

    async with SessionFactory() as session:
        predictions_before = await session.scalar(select(func.count()).select_from(RiskPrediction))
        decisions_before = await session.scalar(select(func.count()).select_from(PolicyDecision))
        report = await InvestigatorService(provider=ThrowingProvider()).investigate(
            session, transaction_id
        )
        assert report.generated_by.value == "DETERMINISTIC"
        assert report.llm_status.value == "UNAVAILABLE"
        assert (
            await session.scalar(select(func.count()).select_from(RiskPrediction))
            == predictions_before
        )
        assert (
            await session.scalar(select(func.count()).select_from(PolicyDecision))
            == decisions_before
        )
