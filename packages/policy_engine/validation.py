from packages.policy_engine.config import PolicyConfig
from packages.policy_engine.costs import CostProfile


def validate_policy_bundle(policy: PolicyConfig, cost_profile: CostProfile) -> None:
    if policy.cost_profile != cost_profile.cost_profile_version:
        raise ValueError("policy cost-profile reference mismatch")
    if policy.verify_threshold > policy.hold_threshold:
        raise ValueError("invalid policy threshold order")
