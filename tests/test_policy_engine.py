import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from apps.api.app.core.enums import PolicyAction, RiskSeverity
from packages.policy_engine.backtest import BacktestExample, evaluate_policy
from packages.policy_engine.config import (
    OperatingConstraints,
    PolicyConfig,
    load_operating_constraints,
    load_policy_config,
)
from packages.policy_engine.costs import expected_cost_paise, load_cost_profile
from packages.policy_engine.domain import GraphEvidence, PolicyInput
from packages.policy_engine.engine import PolicyEngine
from packages.policy_engine.optimizer import (
    NoFeasiblePolicyError,
    constraint_violations,
    optimize_thresholds,
    threshold_candidates,
)


def _input(
    score: float,
    *,
    signals: tuple[str, ...] = (),
    cluster: str | None = None,
    transaction_id: str = "txn_fixture",
) -> PolicyInput:
    return PolicyInput(
        transaction_public_id=transaction_id,
        model_version="risk-lgbm-v2",
        model_score=score,
        feature_version="features-v1",
        graph_version="graph-v1",
        graph_structure_score=0.7 if signals else 0.0,
        graph_signals=tuple(
            GraphEvidence(
                code=code,
                strength=0.8,
                observed_value=8,
                threshold=3,
                evidence={},
            )
            for code in signals
        ),
        detected_cluster_id=cluster,
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_policy_and_cost_configs_load_deterministically() -> None:
    first = load_policy_config()
    second = load_policy_config()
    cost = load_cost_profile()
    assert first == second
    assert first.stable_hash() == second.stable_hash()
    assert cost.cost_profile_version == "balanced-v1"
    assert "SYNTHETIC" in cost.assumptions_label


def test_policy_versions_are_distinct_and_v1_remains_loadable() -> None:
    policy_v1 = load_policy_config(version="risk-policy-v1")
    policy_v2 = load_policy_config(version="risk-policy-v2")
    assert policy_v1.policy_version == "risk-policy-v1"
    assert policy_v2.policy_version == "risk-policy-v2"
    assert policy_v1 != policy_v2
    assert policy_v2.cost_profile == "balanced-v1"


def test_invalid_thresholds_and_versions_fail_closed() -> None:
    raw = load_policy_config().model_dump()
    raw.update({"verify_threshold": 0.8, "hold_threshold": 0.2})
    with pytest.raises(ValidationError, match="verify_threshold"):
        PolicyConfig.model_validate(raw)
    raw.update({"verify_threshold": 0.1, "hold_threshold": 0.2, "model_version": "wrong"})
    with pytest.raises(ValidationError, match="risk-lgbm-v2"):
        PolicyConfig.model_validate(raw)


def test_runtime_policy_input_excludes_outcome_and_truth() -> None:
    payload = _input(0.1).model_dump()
    for forbidden in ("status", "failure_code", "ground_truth_label", "ring_id", "persona"):
        with pytest.raises(ValidationError):
            PolicyInput.model_validate({**payload, forbidden: "forbidden"})


def test_frozen_upstream_artifacts_are_unchanged() -> None:
    expected = {
        "ml/artifacts/features-v1/schema.json": (
            "0593bc8c4b3b7cd041de987cc76747952bf2e7de7d0ac1cf61bf93c603379795"
        ),
        "ml/artifacts/graph-v1/schema.json": (
            "51f187db773dd3c829dfb5b1b00e3e384d0483073e193f0ccb6797accb03c433"
        ),
        "ml/artifacts/model-v2/model.txt": (
            "7da59f3ef52ba2378fb9799c398d0a144e82e30e9fa8084d26d034d85883c5a7"
        ),
        "configs/scenarios/hardened-v2.yaml": (
            "43133e6fedfdcdc6e4a97d7922dbdb4db109c1bc103ac7eebe061b8620ba21ab"
        ),
    }
    for filename, digest in expected.items():
        assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == digest


def test_score_bands_are_bounded_actions() -> None:
    config = load_policy_config().model_copy(
        update={"verify_threshold": 0.2, "hold_threshold": 0.7}
    )
    engine = PolicyEngine(config)
    low = engine.assess(_input(0.1))[1]
    medium = engine.assess(_input(0.4))[1]
    high = engine.assess(_input(0.8))[1]
    assert (low.action, low.severity) == (PolicyAction.ALLOW, RiskSeverity.LOW)
    assert (medium.action, medium.severity) == (PolicyAction.VERIFY, RiskSeverity.MEDIUM)
    assert (high.action, high.severity) == (PolicyAction.HOLD, RiskSeverity.HIGH)


def test_graph_corroboration_only_escalates_an_existing_hold() -> None:
    config = load_policy_config().model_copy(
        update={"verify_threshold": 0.2, "hold_threshold": 0.7}
    )
    signals = (
        "DEVICE_MULTI_CUSTOMER_CONCENTRATION",
        "RAPID_RELATIONSHIP_EXPANSION",
    )
    engine = PolicyEngine(config)
    assert engine.assess(_input(0.1, signals=signals))[1].action == PolicyAction.ALLOW
    decision = engine.assess(_input(0.8, signals=signals))[1]
    assert decision.action == PolicyAction.ESCALATE
    assert decision.requires_human_review is True


@pytest.mark.parametrize("code", ("IP_SHARING_ONLY", "ADDRESS_SHARING_ONLY"))
def test_single_ip_or_address_evidence_cannot_escalate(code: str) -> None:
    decision = PolicyEngine(load_policy_config()).assess(_input(0.99, signals=(code,)))[1]
    assert decision.action == PolicyAction.HOLD


def test_recommend_block_requires_cluster_multiple_signals_and_human_review() -> None:
    signals = (
        "DEVICE_MULTI_CUSTOMER_CONCENTRATION",
        "DEVICE_MULTI_INSTRUMENT_CONCENTRATION",
        "RAPID_RELATIONSHIP_EXPANSION",
    )
    engine = PolicyEngine(load_policy_config())
    without_cluster = engine.assess(_input(0.99, signals=signals))[1]
    with_cluster = engine.assess(_input(0.99, signals=signals, cluster="clu_fixture"))[1]
    assert without_cluster.action == PolicyAction.ESCALATE
    assert with_cluster.action == PolicyAction.RECOMMEND_BLOCK
    assert with_cluster.requires_human_review is True
    assert engine.assess(_input(0.99, cluster="clu_fixture"))[1].action == PolicyAction.HOLD


def test_cost_model_known_fixture_and_allow_all_baseline() -> None:
    profile = load_cost_profile()
    remaining, friction, operational = expected_cost_paise(
        amount_paise=100_000,
        is_abuse=True,
        action=PolicyAction.HOLD,
        profile=profile,
    )
    assert (remaining, friction, operational) == (25_000, 0, 100)
    examples = (
        BacktestExample(_input(0.0, transaction_id="legit"), 100_000, 0),
        BacktestExample(_input(0.0, transaction_id="abuse"), 200_000, 1),
    )
    report = evaluate_policy(examples, load_policy_config(), profile)
    assert report["costs_paise"]["allow_all_baseline_expected_loss"] == 200_000
    assert report["costs_paise"]["total_policy_expected_cost"] == 200_000
    assert report["costs_paise"]["estimated_net_protected_value"] == 0


def test_optimizer_is_deterministic_and_has_no_test_argument() -> None:
    profile = load_cost_profile()
    base = load_policy_config()
    validation = tuple(
        BacktestExample(_input(score, transaction_id=f"txn_{index}"), 100_000, label)
        for index, (score, label) in enumerate(((0.01, 0), (0.02, 0), (0.2, 1), (0.7, 1), (0.9, 1)))
    )
    first = optimize_thresholds(validation, base, profile)
    second = optimize_thresholds(validation, base, profile)
    assert first.policy == second.policy
    assert first.frontier == second.frontier
    assert first.policy.verify_threshold < first.policy.hold_threshold


def test_operating_constraints_validate_ranges() -> None:
    constraints = load_operating_constraints()
    assert constraints.assumptions_label == "ILLUSTRATIVE SYNTHETIC OPERATING ASSUMPTIONS"
    raw = constraints.model_dump()
    for field in (
        "minimum_abuse_intervention_recall",
        "maximum_legitimate_intervention_rate",
        "maximum_legitimate_severe_intervention_rate",
        "maximum_total_human_review_rate",
        "maximum_any_legitimate_persona_severe_intervention_rate",
    ):
        with pytest.raises(ValidationError):
            OperatingConstraints.model_validate({**raw, field: -0.01})
        with pytest.raises(ValidationError):
            OperatingConstraints.model_validate({**raw, field: 1.01})


@pytest.mark.parametrize(
    ("metric", "value", "expected"),
    (
        ("abuse_intervention_recall", 0.94, "minimum_abuse_intervention_recall"),
        ("legitimate_intervention_rate", 0.051, "maximum_legitimate_intervention_rate"),
        (
            "legitimate_severe_intervention_rate",
            0.016,
            "maximum_legitimate_severe_intervention_rate",
        ),
        ("total_human_review_rate", 0.021, "maximum_total_human_review_rate"),
        (
            "maximum_legitimate_persona_severe_intervention_rate",
            0.101,
            "maximum_any_legitimate_persona_severe_intervention_rate",
        ),
    ),
)
def test_each_operating_constraint_rejects_violations(
    metric: str, value: float, expected: str
) -> None:
    operating = {
        "abuse_intervention_recall": 0.96,
        "legitimate_intervention_rate": 0.04,
        "legitimate_severe_intervention_rate": 0.01,
        "total_human_review_rate": 0.01,
        "maximum_legitimate_persona_severe_intervention_rate": 0.05,
    }
    operating[metric] = value
    assert expected in constraint_violations(
        {"operating_metrics": operating}, load_operating_constraints()
    )


def test_zero_feasible_candidates_fails_without_constraint_relaxation() -> None:
    profile = load_cost_profile()
    base = load_policy_config()
    constraints = load_operating_constraints().model_copy(
        update={
            "minimum_abuse_intervention_recall": 1.0,
            "maximum_legitimate_intervention_rate": 0.0,
        }
    )
    validation = (
        BacktestExample(_input(0.9, transaction_id="legit"), 100_000, 0, "TRAVELLER"),
        BacktestExample(_input(0.1, transaction_id="abuse"), 100_000, 1),
    )
    with pytest.raises(NoFeasiblePolicyError, match="BALANCED-V2 INFEASIBLE") as error:
        optimize_thresholds(
            validation,
            base,
            profile,
            constraints=constraints,
            quantile_count=5,
        )
    assert error.value.diagnostics["feasible_candidate_count"] == 0
    assert error.value.diagnostics["nearest_candidates"]


def test_candidate_generation_and_constrained_optimizer_are_deterministic() -> None:
    scores = np.asarray([0.01, 0.02, 0.3, 0.8, 0.9])
    assert threshold_candidates(scores, quantile_count=5) == threshold_candidates(
        scores, quantile_count=5
    )
    validation = tuple(
        BacktestExample(
            _input(score, transaction_id=f"constrained_{index}"),
            100_000,
            label,
            "STANDARD_RETAIL" if not label else None,
        )
        for index, (score, label) in enumerate(
            ((0.01, 0), (0.02, 0), (0.03, 0), (0.30, 1), (0.80, 1), (0.90, 1))
        )
    )
    constraints = load_operating_constraints().model_copy(
        update={
            "minimum_abuse_intervention_recall": 0.66,
            "maximum_legitimate_intervention_rate": 0.34,
            "maximum_legitimate_severe_intervention_rate": 0.34,
            "maximum_total_human_review_rate": 1.0,
            "maximum_any_legitimate_persona_severe_intervention_rate": 0.34,
        }
    )
    kwargs = {
        "constraints": constraints,
        "quantile_count": 7,
        "additional_thresholds": (0.25,),
    }
    first = optimize_thresholds(validation, load_policy_config(), load_cost_profile(), **kwargs)
    second = optimize_thresholds(validation, load_policy_config(), load_cost_profile(), **kwargs)
    assert first == second
    assert first.feasible_candidate_count > 0
    assert first.policy.verify_threshold < first.policy.hold_threshold
    assert first.validation_metrics["action_counts"]["VERIFY"] > 0
    assert first.validation_metrics["costs_paise"]["total_policy_expected_cost"] == min(
        item["total_policy_expected_cost"] for item in first.frontier
    )


def test_unrelated_test_labels_cannot_change_validation_thresholds() -> None:
    profile = load_cost_profile()
    base = load_policy_config()
    validation = tuple(
        BacktestExample(_input(score, transaction_id=f"validation_{index}"), 100_000, label)
        for index, (score, label) in enumerate(((0.01, 0), (0.1, 0), (0.4, 1), (0.9, 1)))
    )
    first = optimize_thresholds(validation, base, profile).policy
    unrelated_test = tuple(
        BacktestExample(_input(score, transaction_id=f"test_{index}"), 100_000, label)
        for index, (score, label) in enumerate(((0.2, 0), (0.8, 1)))
    )
    flipped_test = tuple(
        BacktestExample(item.policy_input, item.amount_paise, 1 - item.label)
        for item in unrelated_test
    )
    assert unrelated_test != flipped_test
    second = optimize_thresholds(validation, base, profile).policy
    assert first == second


def test_sensitivity_profiles_are_distinct_valid_assumptions() -> None:
    roots = Path("configs/costs")
    profiles = [
        load_cost_profile(roots / name)
        for name in (
            "balanced-v1.yaml",
            "customer-protective-v1.yaml",
            "loss-averse-v1.yaml",
        )
    ]
    assert len({profile.stable_hash() for profile in profiles}) == 3


def test_frozen_policy_artifacts_preserve_ordering_and_test_seal() -> None:
    artifact_root = Path("ml/artifacts/policy-v1")
    freeze = json.loads((artifact_root / "freeze.json").read_text(encoding="utf-8"))
    metadata = json.loads((artifact_root / "metadata.json").read_text(encoding="utf-8"))
    validation = json.loads((artifact_root / "validation_metrics.json").read_text(encoding="utf-8"))
    test = json.loads((artifact_root / "test_metrics.json").read_text(encoding="utf-8"))
    policy = load_policy_config(version="risk-policy-v1")

    assert freeze["checkpoint"] == "RISK-POLICY-V1 FROZEN"
    assert freeze["test_evaluated_at_checkpoint"] is False
    assert datetime.fromisoformat(metadata["test_evaluated_at"]) > datetime.fromisoformat(
        freeze["frozen_at"]
    )
    assert freeze["policy_config_hash"] == policy.stable_hash()
    assert freeze["verify_threshold"] == policy.verify_threshold
    assert freeze["hold_threshold"] == policy.hold_threshold
    assert policy.verify_threshold < policy.hold_threshold
    assert validation["action_counts"]["VERIFY"] > 0
    assert sum(test["action_counts"].values()) == 7_500


def test_frozen_policy_limits_household_and_corporate_severe_interventions() -> None:
    test = json.loads(Path("ml/artifacts/policy-v1/test_metrics.json").read_text(encoding="utf-8"))
    personas = test["persona_actions"]
    assert personas["FAMILY_HOUSEHOLD"]["severe_intervention_rate"] < 0.10
    assert personas["CORPORATE_OR_CAMPUS_NETWORK"]["severe_intervention_rate"] < 0.02


def test_policy_v2_freeze_precedes_external_seed_and_satisfies_constraints() -> None:
    artifact_root = Path("ml/artifacts/policy-v2")
    freeze = json.loads((artifact_root / "freeze.json").read_text(encoding="utf-8"))
    validation = json.loads((artifact_root / "validation_metrics.json").read_text(encoding="utf-8"))
    policy = load_policy_config(version="risk-policy-v2")
    constraints = load_operating_constraints()
    operating = validation["operating_metrics"]

    assert freeze["checkpoint"] == "RISK-POLICY-V2 FROZEN"
    assert freeze["external_evaluation_seed"] == 91573
    assert freeze["external_seed_evaluated_at_checkpoint"] is False
    assert freeze["policy_config_hash"] == policy.stable_hash()
    assert freeze["operating_constraints_hash"] == constraints.stable_hash()
    assert freeze["feasible_candidate_count"] > 0
    assert policy.verify_threshold < policy.hold_threshold
    assert validation["action_counts"]["VERIFY"] > 0
    assert operating["abuse_intervention_recall"] >= constraints.minimum_abuse_intervention_recall
    assert (
        operating["legitimate_intervention_rate"]
        <= constraints.maximum_legitimate_intervention_rate
    )
    assert (
        operating["legitimate_severe_intervention_rate"]
        <= constraints.maximum_legitimate_severe_intervention_rate
    )
    assert operating["total_human_review_rate"] <= constraints.maximum_total_human_review_rate
    assert (
        operating["maximum_legitimate_persona_severe_intervention_rate"]
        <= constraints.maximum_any_legitimate_persona_severe_intervention_rate
    )


def test_external_evaluator_requires_the_frozen_policy_bundle(tmp_path: Path) -> None:
    from scripts.build_policy_v2_artifacts import _assert_frozen_bundle

    with pytest.raises(FileNotFoundError):
        _assert_frozen_bundle(tmp_path)
    policy, constraints, cost, freeze = _assert_frozen_bundle(Path("ml/artifacts/policy-v2"))
    assert policy.policy_version == "risk-policy-v2"
    assert constraints.assumptions_label == "ILLUSTRATIVE SYNTHETIC OPERATING ASSUMPTIONS"
    assert cost.cost_profile_version == "balanced-v1"
    assert (policy.verify_threshold, policy.hold_threshold) == (
        freeze["verify_threshold"],
        freeze["hold_threshold"],
    )


def test_external_evaluation_did_not_change_frozen_thresholds() -> None:
    root = Path("ml/artifacts/policy-v2")
    freeze = json.loads((root / "freeze.json").read_text(encoding="utf-8"))
    external = json.loads((root / "external_metrics.json").read_text(encoding="utf-8"))
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    policy = load_policy_config(version="risk-policy-v2")
    assert datetime.fromisoformat(external["evaluated_at"]) > datetime.fromisoformat(
        freeze["frozen_at"]
    )
    assert metadata["external_evaluation"]["seed"] == 91573
    assert policy.verify_threshold == freeze["verify_threshold"]
    assert policy.hold_threshold == freeze["hold_threshold"]
    assert policy.stable_hash() == freeze["policy_config_hash"]
