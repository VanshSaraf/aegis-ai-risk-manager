from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from apps.api.app.core.enums import PolicyAction
from packages.policy_engine.config import PolicyConfig
from packages.policy_engine.costs import CostProfile, expected_cost_paise
from packages.policy_engine.domain import PolicyInput
from packages.policy_engine.engine import PolicyEngine

SEVERE_ACTIONS = {
    PolicyAction.HOLD,
    PolicyAction.ESCALATE,
    PolicyAction.RECOMMEND_BLOCK,
}
HUMAN_REVIEW_ACTIONS = {
    PolicyAction.ESCALATE,
    PolicyAction.RECOMMEND_BLOCK,
}


@dataclass(frozen=True, slots=True)
class BacktestExample:
    """Offline-only record. Truth and slices never enter PolicyInput or PolicyEngine."""

    policy_input: PolicyInput
    amount_paise: int
    label: int
    persona: str | None = None
    scenario: str | None = None


def _classification(tp: int, fp: int, tn: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
    }


def evaluate_policy(
    examples: tuple[BacktestExample, ...],
    policy: PolicyConfig,
    cost_profile: CostProfile,
) -> dict[str, Any]:
    if policy.cost_profile != cost_profile.cost_profile_version:
        raise ValueError("policy and cost-profile versions do not match")
    engine = PolicyEngine(policy)
    actions: list[PolicyAction] = []
    action_counts: Counter[str] = Counter()
    legitimate_action_details: dict[str, dict[str, int]] = {
        action.value: {
            "transaction_count": 0,
            "amount_paise": 0,
            "friction_cost_paise": 0,
            "operational_cost_paise": 0,
        }
        for action in PolicyAction
        if action != PolicyAction.ALLOW
    }
    persona_actions: dict[str, Counter[str]] = defaultdict(Counter)
    scenario_actions: dict[str, Counter[str]] = defaultdict(Counter)
    total_amount = legitimate_amount = abuse_amount = 0
    legitimate_touched = abuse_touched = abuse_allowed = 0
    remaining_abuse_loss = legitimate_friction = operational_cost = 0

    for example in examples:
        _, decision = engine.assess(example.policy_input)
        action = decision.action
        actions.append(action)
        action_counts[action.value] += 1
        if example.persona and not example.label:
            persona_actions[example.persona][action.value] += 1
        if example.label and example.scenario:
            scenario_actions[example.scenario][action.value] += 1
        amount = example.amount_paise
        total_amount += amount
        if example.label:
            abuse_amount += amount
            if action == PolicyAction.ALLOW:
                abuse_allowed += amount
            else:
                abuse_touched += amount
        else:
            legitimate_amount += amount
            if action != PolicyAction.ALLOW:
                legitimate_touched += amount
        remaining, friction, operational = expected_cost_paise(
            amount_paise=amount,
            is_abuse=bool(example.label),
            action=action,
            profile=cost_profile,
        )
        remaining_abuse_loss += remaining
        legitimate_friction += friction
        operational_cost += operational
        if not example.label and action != PolicyAction.ALLOW:
            detail = legitimate_action_details[action.value]
            detail["transaction_count"] += 1
            detail["amount_paise"] += amount
            detail["friction_cost_paise"] += friction
            detail["operational_cost_paise"] += operational

    intervention = [action != PolicyAction.ALLOW for action in actions]
    severe = [action in SEVERE_ACTIONS for action in actions]
    labels = [bool(example.label) for example in examples]

    def confusion(predictions: list[bool]) -> tuple[int, int, int, int]:
        pairs = tuple(zip(predictions, labels, strict=True))
        tp = sum(prediction and label for prediction, label in pairs)
        fp = sum(prediction and not label for prediction, label in pairs)
        tn = sum(
            not prediction and not label
            for prediction, label in zip(predictions, labels, strict=True)
        )
        fn = sum(
            not prediction and label for prediction, label in zip(predictions, labels, strict=True)
        )
        return tp, fp, tn, fn

    intervention_metrics = _classification(*confusion(intervention))
    severe_metrics = _classification(*confusion(severe))
    legitimate_count = sum(not label for label in labels)
    abuse_count = sum(labels)
    human_review_count = sum(action in HUMAN_REVIEW_ACTIONS for action in actions)
    baseline_loss = round(abuse_amount * cost_profile.abuse_loss_fraction)
    policy_cost = remaining_abuse_loss + legitimate_friction + operational_cost

    def slice_report(groups: dict[str, Counter[str]]) -> dict[str, dict[str, float | int]]:
        output: dict[str, dict[str, float | int]] = {}
        for group, counts in sorted(groups.items()):
            total = sum(counts.values())
            severe_count = sum(counts[action.value] for action in SEVERE_ACTIONS)
            output[group] = {
                "transactions": total,
                **{action.value: counts[action.value] for action in PolicyAction},
                "severe_intervention_rate": severe_count / total if total else 0.0,
                "intervention_rate": (
                    (total - counts[PolicyAction.ALLOW.value]) / total if total else 0.0
                ),
            }
        return output

    persona_report = slice_report(persona_actions)
    max_persona_name, max_persona_rate = max(
        (
            (persona, float(values["severe_intervention_rate"]))
            for persona, values in persona_report.items()
        ),
        key=lambda item: (item[1], item[0]),
        default=(None, 0.0),
    )

    return {
        "policy_version": policy.policy_version,
        "policy_config_hash": policy.stable_hash(),
        "cost_profile_version": cost_profile.cost_profile_version,
        "cost_profile_hash": cost_profile.stable_hash(),
        "assumptions_label": cost_profile.assumptions_label,
        "thresholds": {
            "verify_threshold": policy.verify_threshold,
            "hold_threshold": policy.hold_threshold,
        },
        "action_counts": {action.value: action_counts[action.value] for action in PolicyAction},
        "intervention": intervention_metrics,
        "severe_intervention": severe_metrics,
        "operating_metrics": {
            "abuse_intervention_recall": intervention_metrics["recall"],
            "legitimate_intervention_rate": (
                intervention_metrics["false_positive"] / legitimate_count
                if legitimate_count
                else 0.0
            ),
            "legitimate_severe_intervention_rate": (
                severe_metrics["false_positive"] / legitimate_count if legitimate_count else 0.0
            ),
            "total_human_review_rate": human_review_count / len(examples) if examples else 0.0,
            "human_review_count": human_review_count,
            "legitimate_count": legitimate_count,
            "abuse_count": abuse_count,
            "maximum_legitimate_persona_severe_intervention_rate": max_persona_rate,
            "maximum_legitimate_persona": max_persona_name,
        },
        "amounts_paise": {
            "total_transaction_amount": total_amount,
            "total_legitimate_amount": legitimate_amount,
            "total_abuse_amount": abuse_amount,
            "legitimate_amount_touched": legitimate_touched,
            "abuse_amount_touched": abuse_touched,
            "abuse_amount_allowed": abuse_allowed,
            "amount_weighted_abuse_intervention_rate": (
                abuse_touched / abuse_amount if abuse_amount else 0.0
            ),
        },
        "costs_paise": {
            "allow_all_baseline_expected_loss": baseline_loss,
            "remaining_abuse_loss": remaining_abuse_loss,
            "legitimate_intervention_friction_cost": legitimate_friction,
            "operational_action_cost": operational_cost,
            "total_policy_expected_cost": policy_cost,
            "estimated_net_protected_value": baseline_loss - policy_cost,
        },
        "legitimate_intervention_by_action": legitimate_action_details,
        "persona_actions": persona_report,
        "scenario_actions": slice_report(scenario_actions),
    }
