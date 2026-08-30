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
