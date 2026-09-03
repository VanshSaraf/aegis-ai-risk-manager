from apps.api.app.core.enums import PolicyAction
from packages.investigator.domain import EvidenceBundle

NEXT_STEPS = {
    PolicyAction.ALLOW: "No additional intervention recommended.",
    PolicyAction.VERIFY: "Proceed with configured step-up verification.",
    PolicyAction.HOLD: "Maintain the temporary review hold.",
    PolicyAction.ESCALATE: "Route the transaction to human risk review.",
    PolicyAction.RECOMMEND_BLOCK: ("A human reviewer should evaluate the block recommendation."),
}


def summary(bundle: EvidenceBundle) -> str:
    return (
        f"Aegis assigned {bundle.policy.action.value} because the frozen risk-lgbm-v2 score "
        f"entered the corresponding risk-policy-v2 action band."
    )


def decision_explanation(bundle: EvidenceBundle) -> str:
    action = bundle.policy.action
    if action in {PolicyAction.ESCALATE, PolicyAction.RECOMMEND_BLOCK}:
        return (
            f"The model score first entered the HOLD band. Graph-v1 evidence then corroborated "
            f"that existing HOLD and satisfied the deterministic requirements for {action.value}. "
            "Graph evidence did not independently create the underlying HOLD."
        )
    if action == PolicyAction.HOLD:
        return (
            "The model score entered the HOLD band. Graph evidence did not independently create "
            "the HOLD; it is shown only as supporting structural context."
        )
    if action == PolicyAction.VERIFY:
        return (
            "The model score entered the intermediate VERIFY band. Graph evidence cannot promote "
            "VERIFY directly to a severe action under risk-policy-v2."
        )
    return (
        "The model score remained below the VERIFY threshold. Graph evidence cannot promote an "
        "ALLOW directly to a severe action under risk-policy-v2."
    )


def why_not_stronger(bundle: EvidenceBundle) -> str:
    action = bundle.policy.action
    policy = bundle.policy
    score = bundle.model.score
    if action == PolicyAction.ALLOW:
        return (
            f"The model score {score:.4f} remains below the frozen VERIFY boundary "
            f"{policy.verify_threshold:.4f}."
        )
    if action == PolicyAction.VERIFY:
        return (
            f"The model score {score:.4f} remains below the frozen HOLD boundary "
            f"{policy.hold_threshold:.4f}. Graph evidence cannot create a HOLD on its own."
        )
    if action == PolicyAction.HOLD:
        strong_count = len(set(bundle.graph.signals) & set(policy.strong_signal_codes))
        return (
            f"The frozen escalation rule requires at least "
            f"{policy.escalation_minimum_strong_signals} strong structural signals. "
            f"This assessment contains {strong_count}; graph-supported escalation was not met."
        )
    if action == PolicyAction.ESCALATE:
        strong_count = len(set(bundle.graph.signals) & set(policy.strong_signal_codes))
        missing = []
        if strong_count < policy.recommend_block_minimum_strong_signals:
            missing.append(
                f"{policy.recommend_block_minimum_strong_signals} strong signals "
                f"(current: {strong_count})"
            )
        if policy.recommend_block_requires_active_cluster and bundle.cluster is None:
            missing.append("an active Aegis cluster")
        if missing:
            return "RECOMMEND_BLOCK additionally requires " + " and ".join(missing) + "."
        return "The persisted policy reasons do not support a stronger recommendation."
    return (
        "RECOMMEND_BLOCK is the strongest bounded Aegis recommendation. A human reviewer must "
        "decide whether any external action is appropriate."
    )


def graph_narrative(bundle: EvidenceBundle) -> str:
    if not bundle.graph.signals:
        return (
            f"Graph-v1 structural score was {bundle.graph.structural_score:.4f}; no named strong "
            "graph signal was present in the immutable assessment snapshot."
        )
    readable = ", ".join(code.replace("_", " ").lower() for code in bundle.graph.signals)
    return (
        f"Graph-v1 structural score was {bundle.graph.structural_score:.4f} and raised: "
        f"{readable}. These signals support investigation but do not prove fraud."
    )


def recommended_next_step(bundle: EvidenceBundle) -> str:
    return NEXT_STEPS[bundle.policy.action]
