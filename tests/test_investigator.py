from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.api.app.core.enums import PolicyAction, RiskSeverity
from packages.investigator import deterministic
from packages.investigator.domain import (
    DecisionProvenance,
    EntityReferences,
    EvidenceBundle,
    EvidenceCategory,
    EvidenceItem,
    GeneratedBy,
    GraphSummary,
    LLMStatus,
    ModelSummary,
    PolicySummary,
    TransactionSummary,
    VersionMetadata,
)
from packages.investigator.evidence import REGISTERED_EVIDENCE_CODES, EvidenceBuilder
from packages.investigator.provider import DisabledProvider, provider_from_config
from packages.investigator.service import InvestigatorService


def _bundle(action: PolicyAction = PolicyAction.HOLD) -> EvidenceBundle:
    severity = {
        PolicyAction.ALLOW: RiskSeverity.LOW,
        PolicyAction.VERIFY: RiskSeverity.MEDIUM,
        PolicyAction.HOLD: RiskSeverity.HIGH,
        PolicyAction.ESCALATE: RiskSeverity.CRITICAL,
        PolicyAction.RECOMMEND_BLOCK: RiskSeverity.CRITICAL,
    }[action]
    return EvidenceBundle(
        transaction=TransactionSummary(
            transaction_id="txn_fixture",
            event_time=datetime(2026, 8, 30, tzinfo=UTC),
            amount_paise=100_000,
            formatted_amount="₹1,000.00",
            currency="INR",
            payment_method="CARD",
            entities=EntityReferences(
                customer="cus_safe",
                merchant="mer_safe",
                instrument="ins_safe",
                device="dev_safe",
                ip="ip_safe",
                address="adr_safe",
            ),
        ),
        model=ModelSummary(version="risk-lgbm-v2", score=0.98),
        policy=PolicySummary(
            version="risk-policy-v2",
            action=action,
            severity=severity,
            requires_human_review=action in {PolicyAction.ESCALATE, PolicyAction.RECOMMEND_BLOCK},
            reason_codes=("MODEL_SCORE_HOLD_BAND",),
            verify_threshold=0.1,
            hold_threshold=0.9,
            graph_corroborated=action
            in {
                PolicyAction.ESCALATE,
                PolicyAction.RECOMMEND_BLOCK,
            },
            strong_signal_codes=("DEVICE_MULTI_CUSTOMER_CONCENTRATION",),
            escalation_minimum_strong_signals=2,
            recommend_block_minimum_strong_signals=3,
            recommend_block_requires_active_cluster=True,
        ),
        graph=GraphSummary(
            version="graph-v1",
            structural_score=0.7,
            signals=("DEVICE_MULTI_CUSTOMER_CONCENTRATION",),
            selected_metrics={"device_customer_degree": 5},
        ),
        evidence_items=(
            EvidenceItem(
                code="MODEL_SCORE_POLICY_BAND",
                category=EvidenceCategory.POLICY,
                title="Model score band",
                observed_value=0.98,
                context="The model score entered the configured band.",
                importance=100,
                source="risk model",
                source_version="risk-lgbm-v2",
            ),
        ),
        related_entities=(),
        cluster=None,
        timeline=(),
        limitations=("Evidence does not prove fraud.",),
        versions=VersionMetadata(
            feature_version="features-v1",
            graph_version="graph-v1",
            model_version="risk-lgbm-v2",
            policy_version="risk-policy-v2",
        ),
        provenance=DecisionProvenance(
            event_received_at=datetime(2026, 8, 30, tzinfo=UTC),
            feature_computed_at=datetime(2026, 8, 30, tzinfo=UTC),
            feature_max_source_event_time=None,
            graph_computed_at=datetime(2026, 8, 30, tzinfo=UTC),
            graph_max_source_event_time=None,
            prediction_created_at=datetime(2026, 8, 30, tzinfo=UTC),
            decision_created_at=datetime(2026, 8, 30, tzinfo=UTC),
        ),
    )


class FakeBuilder:
    def __init__(self, bundle: EvidenceBundle) -> None:
        self.bundle = bundle

    async def build(self, session, transaction_id: str) -> EvidenceBundle:
        del session, transaction_id
        return self.bundle


class ThrowingProvider:
    async def generate(self, evidence: EvidenceBundle) -> str:
        del evidence
        raise RuntimeError("provider unavailable")


class SuccessfulProvider:
    async def generate(self, evidence: EvidenceBundle) -> str:
        return f"Supplementary narrative for {evidence.policy.action.value}."


def test_evidence_bundle_rejects_truth_persona_outcome_and_split() -> None:
    payload = _bundle().model_dump()
    serialized = str(payload).lower()
    for forbidden in (
        "ground_truth",
        "persona",
        "scenario",
        "ring_id",
        "split",
        "failure_code",
        "fraud_probability",
    ):
        assert forbidden not in serialized
        with pytest.raises(ValidationError):
            EvidenceBundle.model_validate({**payload, forbidden: "forbidden"})


def test_evidence_selection_is_registered_bounded_and_deterministic() -> None:
    builder = EvidenceBuilder()
    kwargs = {
        "model_score": 0.99,
        "action": PolicyAction.RECOMMEND_BLOCK,
        "reason_codes": ("GRAPH_CORROBORATED", "MODEL_SCORE_HOLD_BAND"),
        "signal_codes": (
            "RAPID_RELATIONSHIP_EXPANSION",
            "DEVICE_MULTI_CUSTOMER_CONCENTRATION",
        ),
        "features": {
            "device_txn_count_10m": 8,
            "ip_unique_customers_1h": 5,
            "customer_failed_txn_count_1h": 3,
            "is_new_device_for_customer": True,
            "is_new_instrument_for_customer": True,
            "historical_customers_on_current_device": 5,
            "historical_instruments_on_current_device": 7,
        },
        "cluster_id": "clu_safe",
    }
    first = builder._evidence_items(**kwargs)
    second = builder._evidence_items(**kwargs)
    assert first == second
    assert 3 <= len(first) <= 8
    assert all(item.code in REGISTERED_EVIDENCE_CODES for item in first)
    assert [item.importance for item in first] == sorted(
        (item.importance for item in first), reverse=True
    )


@pytest.mark.parametrize("action", tuple(PolicyAction))
def test_deterministic_explanation_preserves_policy_action(action: PolicyAction) -> None:
    bundle = _bundle(action)
    assert action.value in deterministic.summary(bundle)
    expected = {
        PolicyAction.ALLOW: "No additional intervention",
        PolicyAction.VERIFY: "step-up verification",
        PolicyAction.HOLD: "temporary review hold",
        PolicyAction.ESCALATE: "human risk review",
        PolicyAction.RECOMMEND_BLOCK: "block recommendation",
    }[action]
    assert expected in deterministic.recommended_next_step(bundle)


def test_graph_narrative_is_corroborative_and_never_proof() -> None:
    explanation = deterministic.decision_explanation(_bundle(PolicyAction.HOLD))
    graph = deterministic.graph_narrative(_bundle(PolicyAction.HOLD))
    assert "did not independently create" in explanation
    assert "do not prove fraud" in graph
    assert "fraud probability" in _bundle().model.semantics


@pytest.mark.parametrize(
    ("action", "expected"),
    (
        (PolicyAction.ALLOW, "VERIFY boundary"),
        (PolicyAction.VERIFY, "HOLD boundary"),
        (PolicyAction.HOLD, "escalation rule"),
        (PolicyAction.ESCALATE, "RECOMMEND_BLOCK"),
        (PolicyAction.RECOMMEND_BLOCK, "strongest bounded"),
    ),
)
def test_why_not_stronger_is_deterministic_and_policy_bounded(
    action: PolicyAction, expected: str
) -> None:
    explanation = deterministic.why_not_stronger(_bundle(action))
    assert expected in explanation
    assert "fraud probability" not in explanation


@pytest.mark.asyncio
async def test_disabled_missing_key_and_provider_exception_fall_back_deterministically() -> None:
    bundle = _bundle(PolicyAction.ESCALATE)
    providers = (
        DisabledProvider(),
        provider_from_config("openai", None),
        ThrowingProvider(),
    )
    for provider in providers:
        report = await InvestigatorService(
            evidence_builder=FakeBuilder(bundle), provider=provider
        ).investigate(None, bundle.transaction.transaction_id)  # type: ignore[arg-type]
        assert report.generated_by == GeneratedBy.DETERMINISTIC
        assert report.llm_status in {LLMStatus.DISABLED, LLMStatus.UNAVAILABLE}
        assert report.policy.action == PolicyAction.ESCALATE
        assert report.narrative is None


@pytest.mark.asyncio
async def test_valid_injected_provider_is_supplementary() -> None:
    bundle = _bundle(PolicyAction.VERIFY)
    report = await InvestigatorService(
        evidence_builder=FakeBuilder(bundle), provider=SuccessfulProvider()
    ).investigate(None, bundle.transaction.transaction_id)  # type: ignore[arg-type]
    assert report.generated_by == GeneratedBy.LLM
    assert report.llm_status == LLMStatus.AVAILABLE
    assert report.narrative == "Supplementary narrative for VERIFY."
    assert report.policy == bundle.policy
    assert report.evidence == bundle.evidence_items
