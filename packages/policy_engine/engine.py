from apps.api.app.core.enums import PolicyAction, RiskSeverity
from packages.policy_engine.config import PolicyConfig
from packages.policy_engine.domain import PolicyDecisionResult, PolicyInput, RiskAssessment
from packages.policy_engine.rules import score_band, strong_graph_signal_codes


class PolicyEngine:
    """Deterministic evidence-gated policy; performs no external payment action."""

    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    def assess(self, policy_input: PolicyInput) -> tuple[RiskAssessment, PolicyDecisionResult]:
        if (
            policy_input.model_version != self.config.model_version
            or policy_input.feature_version != self.config.feature_version
            or policy_input.graph_version != self.config.graph_version
        ):
            raise ValueError("policy input version mismatch")

        base_action, severity, band_reason = score_band(policy_input.model_score, self.config)
        strong_codes = strong_graph_signal_codes(policy_input.graph_signals, self.config)
        corroborated = len(strong_codes) >= self.config.graph_corroboration.minimum_strong_signals
        action = base_action
        reasons = [band_reason]
        if corroborated:
            reasons.extend(("GRAPH_CORROBORATED", "MULTIPLE_STRUCTURAL_SIGNALS"))

        # Graph evidence never moves ALLOW/VERIFY directly to a severe intervention.
        if base_action == PolicyAction.HOLD and corroborated:
            action = PolicyAction.ESCALATE
            severity = RiskSeverity.CRITICAL
            reasons.append("GRAPH_CORROBORATED_ESCALATION")
            graph_config = self.config.graph_corroboration
            cluster_required = graph_config.recommend_block_requires_active_cluster
            cluster_satisfied = bool(policy_input.detected_cluster_id) or not cluster_required
            if (
                cluster_satisfied
                and len(strong_codes) >= graph_config.recommend_block_minimum_strong_signals
            ):
                action = PolicyAction.RECOMMEND_BLOCK
                reasons.extend(("ACTIVE_CLUSTER_CORROBORATION", "HUMAN_REVIEW_RECOMMENDATION"))

        requires_review = action in set(self.config.human_review_actions)
        if action == PolicyAction.RECOMMEND_BLOCK and not requires_review:
            raise RuntimeError("RECOMMEND_BLOCK cannot bypass human review")

        rule_signals = (f"MODEL_RISK_BAND:{severity.value}",) + tuple(
            f"GRAPH_SIGNAL:{code}" for code in strong_codes
        )
        if policy_input.detected_cluster_id:
            rule_signals += ("ACTIVE_CLUSTER",)
        assessment = RiskAssessment(
            **policy_input.model_dump(),
            severity=severity,
            rule_signals=rule_signals,
            policy_context={
                "policy_version": self.config.policy_version,
                "verify_threshold": self.config.verify_threshold,
                "hold_threshold": self.config.hold_threshold,
                "score_semantics": "uncalibrated model score; not a fraud probability",
            },
        )
        decision = PolicyDecisionResult(
            transaction_public_id=policy_input.transaction_public_id,
            policy_version=self.config.policy_version,
            action=action,
            severity=severity,
            requires_human_review=requires_review,
            reason_codes=tuple(dict.fromkeys(reasons)),
            model_score=policy_input.model_score,
            graph_corroborated=corroborated,
            detected_cluster_id=policy_input.detected_cluster_id,
        )
        return assessment, decision
