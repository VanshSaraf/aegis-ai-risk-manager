from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.app.core.enums import GroundTruthLabel, ScenarioType


class TrustedSyntheticContext(BaseModel):
    """Internal-only metadata accepted from the synthetic generation service."""

    model_config = ConfigDict(extra="forbid")

    scenario_run_public_id: str = Field(min_length=1, max_length=64)
    label: GroundTruthLabel
    scenario_type: ScenarioType
    ring_id: str | None = Field(default=None, max_length=255)
    persona: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def truth_is_consistent(self) -> Self:
        if self.label == GroundTruthLabel.LEGITIMATE:
            if self.scenario_type != ScenarioType.NORMAL_TRAFFIC or self.ring_id is not None:
                raise ValueError("legitimate truth must be NORMAL_TRAFFIC without a ring ID")
            if self.persona is None:
                raise ValueError("legitimate synthetic truth requires a persona")
        else:
            if self.scenario_type == ScenarioType.NORMAL_TRAFFIC or not self.ring_id:
                raise ValueError("coordinated abuse requires an abuse scenario and ring ID")
            if self.persona is not None:
                raise ValueError("abuse truth cannot carry a legitimate persona")
        return self
