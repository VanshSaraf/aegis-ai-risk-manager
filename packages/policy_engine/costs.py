import hashlib
import json
import math
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.app.core.enums import PolicyAction

DEFAULT_COST_PATH = Path(__file__).parents[2] / "configs/costs/balanced-v1.yaml"


class CostModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionCost(CostModel):
    legitimate_fixed_cost_paise: int = Field(ge=0)
    legitimate_friction_fraction: float = Field(ge=0, le=1)
    operational_cost_paise: int = Field(ge=0)
    abuse_intervention_effectiveness: float = Field(ge=0, le=1)


class CostProfile(CostModel):
    cost_profile_version: str
    assumptions_label: str
    currency: str
    abuse_loss_fraction: float = Field(ge=0, le=1)
    actions: dict[PolicyAction, ActionCost]

    @model_validator(mode="after")
    def valid_profile(self) -> Self:
        if self.assumptions_label != "ILLUSTRATIVE SYNTHETIC POLICY ASSUMPTIONS":
            raise ValueError("cost profile must explicitly identify synthetic assumptions")
        if self.currency != "INR":
            raise ValueError("policy-v1 cost reporting supports INR only")
        if set(self.actions) != set(PolicyAction):
            raise ValueError("cost profile must define every policy action")
        allow = self.actions[PolicyAction.ALLOW]
        if any(
            (
                allow.legitimate_fixed_cost_paise,
                allow.legitimate_friction_fraction,
                allow.operational_cost_paise,
                allow.abuse_intervention_effectiveness,
            )
        ):
            raise ValueError("ALLOW must have zero intervention cost and effectiveness")
        values = [self.abuse_loss_fraction]
        values.extend(
            value
            for action in self.actions.values()
            for value in (
                action.legitimate_friction_fraction,
                action.abuse_intervention_effectiveness,
            )
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("cost fractions must be finite")
        return self

    def stable_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def load_cost_profile(path: Path | None = None) -> CostProfile:
    raw = yaml.safe_load((path or DEFAULT_COST_PATH).read_text(encoding="utf-8"))
    return CostProfile.model_validate(raw)


def expected_cost_paise(
    *, amount_paise: int, is_abuse: bool, action: PolicyAction, profile: CostProfile
) -> tuple[int, int, int]:
    """Return remaining abuse loss, legitimate friction, and operational cost."""

    assumptions = profile.actions[action]
    operational = assumptions.operational_cost_paise if action != PolicyAction.ALLOW else 0
    if is_abuse:
        baseline_loss = amount_paise * profile.abuse_loss_fraction
        remaining = round(baseline_loss * (1 - assumptions.abuse_intervention_effectiveness))
        return remaining, 0, operational
    friction = assumptions.legitimate_fixed_cost_paise + round(
        amount_paise * assumptions.legitimate_friction_fraction
    )
    return 0, friction, operational
