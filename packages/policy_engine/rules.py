from apps.api.app.core.enums import PolicyAction, RiskSeverity
from packages.policy_engine.config import PolicyConfig
from packages.policy_engine.domain import GraphEvidence


def score_band(score: float, config: PolicyConfig) -> tuple[PolicyAction, RiskSeverity, str]:
    if score < config.verify_threshold:
        return PolicyAction.ALLOW, RiskSeverity.LOW, "MODEL_SCORE_BELOW_VERIFY"
    if score < config.hold_threshold:
        return PolicyAction.VERIFY, RiskSeverity.MEDIUM, "MODEL_SCORE_VERIFY_BAND"
    return PolicyAction.HOLD, RiskSeverity.HIGH, "MODEL_SCORE_HOLD_BAND"


def strong_graph_signal_codes(
    signals: tuple[GraphEvidence, ...], config: PolicyConfig
) -> tuple[str, ...]:
    allowed = set(config.graph_corroboration.strong_signal_codes)
    return tuple(sorted({signal.code for signal in signals if signal.code in allowed}))
