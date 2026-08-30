from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

from packages.policy_engine.backtest import BacktestExample, evaluate_policy
from packages.policy_engine.config import OperatingConstraints, PolicyConfig
from packages.policy_engine.costs import CostProfile


class NoFeasiblePolicyError(RuntimeError):
    def __init__(self, diagnostics: dict[str, Any]) -> None:
        super().__init__("BALANCED-V2 INFEASIBLE ON VALIDATION")
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    policy: PolicyConfig
    validation_metrics: dict[str, Any]
    frontier: tuple[dict[str, Any], ...]
    candidate_threshold_count: int
    evaluated_pair_count: int
    feasible_candidate_count: int
    rejected_by_constraint: dict[str, int]
    candidate_generation: str
    objective: str = "minimum validation synthetic total_policy_expected_cost"
    tie_break: str = (
        "lower legitimate amount touched, then lower human-review count, then lower legitimate "
        "severe-intervention count, then fewer total interventions, then higher intervention "
        "precision, then higher verify threshold, then higher hold threshold"
    )


def threshold_candidates(scores: np.ndarray, *, quantile_count: int = 21) -> tuple[float, ...]:
    if scores.ndim != 1 or not len(scores) or not np.isfinite(scores).all():
        raise ValueError("validation scores must be a finite non-empty vector")
    if quantile_count < 2:
        raise ValueError("quantile_count must be at least 2")
    quantiles = np.linspace(0.0, 1.0, quantile_count)
    values = {0.0, 1.0, *(float(value) for value in np.quantile(scores, quantiles))}
    return tuple(sorted(values))


def constraint_violations(
    metrics: dict[str, Any], constraints: OperatingConstraints
) -> tuple[str, ...]:
    operating = metrics["operating_metrics"]
    checks = (
        (
            "minimum_abuse_intervention_recall",
            operating["abuse_intervention_recall"] < constraints.minimum_abuse_intervention_recall,
        ),
        (
            "maximum_legitimate_intervention_rate",
            operating["legitimate_intervention_rate"]
            > constraints.maximum_legitimate_intervention_rate,
        ),
        (
            "maximum_legitimate_severe_intervention_rate",
            operating["legitimate_severe_intervention_rate"]
            > constraints.maximum_legitimate_severe_intervention_rate,
        ),
        (
            "maximum_total_human_review_rate",
            operating["total_human_review_rate"] > constraints.maximum_total_human_review_rate,
        ),
        (
            "maximum_any_legitimate_persona_severe_intervention_rate",
            operating["maximum_legitimate_persona_severe_intervention_rate"]
            > constraints.maximum_any_legitimate_persona_severe_intervention_rate,
        ),
    )
    return tuple(name for name, failed in checks if failed)


def _constraint_distance(metrics: dict[str, Any], constraints: OperatingConstraints) -> float:
    operating = metrics["operating_metrics"]
    return sum(
        (
            max(
                0.0,
                constraints.minimum_abuse_intervention_recall
                - operating["abuse_intervention_recall"],
            ),
            max(
                0.0,
                operating["legitimate_intervention_rate"]
                - constraints.maximum_legitimate_intervention_rate,
            ),
            max(
                0.0,
                operating["legitimate_severe_intervention_rate"]
                - constraints.maximum_legitimate_severe_intervention_rate,
            ),
            max(
                0.0,
                operating["total_human_review_rate"] - constraints.maximum_total_human_review_rate,
            ),
            max(
                0.0,
                operating["maximum_legitimate_persona_severe_intervention_rate"]
                - constraints.maximum_any_legitimate_persona_severe_intervention_rate,
            ),
        )
    )


def optimize_thresholds(
    validation_examples: tuple[BacktestExample, ...],
    base_policy: PolicyConfig,
    cost_profile: CostProfile,
    *,
    constraints: OperatingConstraints | None = None,
    quantile_count: int = 21,
    additional_thresholds: tuple[float, ...] = (),
) -> OptimizationResult:
    """Optimize only the explicitly supplied validation examples."""

    scores = np.asarray([example.policy_input.model_score for example in validation_examples])
    candidates = tuple(
        sorted(
            {
                *threshold_candidates(scores, quantile_count=quantile_count),
                base_policy.verify_threshold,
                base_policy.hold_threshold,
                *additional_thresholds,
            }
        )
    )
    ranked: list[tuple[tuple[float, ...], PolicyConfig, dict[str, Any]]] = []
    rejected: Counter[str] = Counter()
    nearest: list[tuple[float, PolicyConfig, dict[str, Any], tuple[str, ...]]] = []
    evaluated_pair_count = 0
    for verify_threshold in candidates:
        for hold_threshold in candidates:
            if verify_threshold >= hold_threshold:
                continue
            evaluated_pair_count += 1
            policy = base_policy.model_copy(
                update={
                    "verify_threshold": verify_threshold,
                    "hold_threshold": hold_threshold,
                    "cost_profile": cost_profile.cost_profile_version,
                }
            )
            metrics = evaluate_policy(validation_examples, policy, cost_profile)
            if metrics["action_counts"]["VERIFY"] == 0:
                rejected["populated_verify_band"] += 1
                continue
            violations = constraint_violations(metrics, constraints) if constraints else ()
            for violation in violations:
                rejected[violation] += 1
            if violations:
                nearest.append(
                    (_constraint_distance(metrics, constraints), policy, metrics, violations)
                )
                continue
            costs = metrics["costs_paise"]
            amounts = metrics["amounts_paise"]
            actions = metrics["action_counts"]
            operating = metrics["operating_metrics"]
            interventions = len(validation_examples) - actions["ALLOW"]
            key = (
                float(costs["total_policy_expected_cost"]),
                float(amounts["legitimate_amount_touched"]),
                float(operating["human_review_count"]),
                float(metrics["severe_intervention"]["false_positive"]),
                float(interventions),
                -float(metrics["intervention"]["precision"]),
                -verify_threshold,
                -hold_threshold,
            )
            ranked.append((key, policy, metrics))

    candidate_generation = (
        f"{quantile_count} evenly spaced validation-score quantiles plus 0, 1, configured "
        "thresholds, Phase 5 threshold, and risk-policy-v1 thresholds; exact duplicates removed"
        if additional_thresholds
        else f"{quantile_count} evenly spaced validation-score quantiles plus 0, 1 and configured "
        "thresholds; exact duplicates removed"
    )
    if not ranked:
        nearest.sort(key=lambda item: (item[0], item[1].verify_threshold, item[1].hold_threshold))
        diagnostics = {
            "candidate_threshold_count": len(candidates),
            "evaluated_pair_count": evaluated_pair_count,
            "feasible_candidate_count": 0,
            "rejected_by_constraint": dict(sorted(rejected.items())),
            "nearest_candidates": [
                {
                    "verify_threshold": policy.verify_threshold,
                    "hold_threshold": policy.hold_threshold,
                    "violations": list(violations),
                    "operating_metrics": metrics["operating_metrics"],
                    "total_policy_expected_cost": metrics["costs_paise"][
                        "total_policy_expected_cost"
                    ],
                }
                for _, policy, metrics, violations in nearest[:10]
            ],
        }
        raise NoFeasiblePolicyError(diagnostics)

    ranked.sort(key=lambda item: item[0])
    _, best_policy, best_metrics = ranked[0]
    frontier = tuple(
        {
            "verify_threshold": policy.verify_threshold,
            "hold_threshold": policy.hold_threshold,
            "total_policy_expected_cost": metrics["costs_paise"]["total_policy_expected_cost"],
            "estimated_net_protected_value": metrics["costs_paise"][
                "estimated_net_protected_value"
            ],
            "intervention_precision": metrics["intervention"]["precision"],
            "intervention_recall": metrics["intervention"]["recall"],
            "operating_metrics": metrics["operating_metrics"],
        }
        for _, policy, metrics in ranked[:100]
    )
    return OptimizationResult(
        policy=best_policy,
        validation_metrics=best_metrics,
        frontier=frontier,
        candidate_threshold_count=len(candidates),
        evaluated_pair_count=evaluated_pair_count,
        feasible_candidate_count=len(ranked),
        rejected_by_constraint=dict(sorted(rejected.items())),
        candidate_generation=candidate_generation,
    )
