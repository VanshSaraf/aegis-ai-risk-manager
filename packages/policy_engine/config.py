import hashlib
import json
import math
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.app.core.enums import PolicyAction
from packages.graph_engine.registry import GRAPH_VERSION, SIGNAL_DEFINITIONS
from packages.risk_engine.features.registry import FEATURE_VERSION

POLICY_V1_VERSION = "risk-policy-v1"
POLICY_V2_VERSION = "risk-policy-v2"
POLICY_VERSION = POLICY_V2_VERSION
PRIMARY_MODEL_VERSION = "risk-lgbm-v2"
POLICY_DIRECTORY = Path(__file__).parents[2] / "configs/policies"
DEFAULT_POLICY_PATH = POLICY_DIRECTORY / "risk-policy-v2.yaml"


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GraphCorroborationConfig(ConfigModel):
    strong_signal_codes: tuple[str, ...]
    minimum_strong_signals: int = Field(ge=2)
    recommend_block_minimum_strong_signals: int = Field(ge=2)
    recommend_block_requires_active_cluster: bool = True

    @model_validator(mode="after")
    def known_signals(self) -> Self:
        supported = {str(item["code"]) for item in SIGNAL_DEFINITIONS}
        unknown = set(self.strong_signal_codes) - supported
        if unknown:
            raise ValueError(f"unknown graph-v1 signal codes: {sorted(unknown)}")
        if self.recommend_block_minimum_strong_signals < self.minimum_strong_signals:
            raise ValueError("recommend-block evidence cannot be weaker than escalation evidence")
        return self


class PolicyConfig(ConfigModel):
    policy_version: str
    schema_version: str
    model_version: str
    feature_version: str
    graph_version: str
    cost_profile: str
    verify_threshold: float = Field(ge=0, le=1)
    hold_threshold: float = Field(ge=0, le=1)
    graph_corroboration: GraphCorroborationConfig
    human_review_actions: tuple[PolicyAction, ...]

    @model_validator(mode="after")
    def valid_policy(self) -> Self:
        if self.policy_version not in {POLICY_V1_VERSION, POLICY_V2_VERSION}:
            raise ValueError("unsupported policy version")
        if self.schema_version != "policy-schema-v1":
            raise ValueError("unsupported policy version/schema")
        if self.model_version != PRIMARY_MODEL_VERSION:
            raise ValueError("policy requires risk-lgbm-v2")
        if self.feature_version != FEATURE_VERSION or self.graph_version != GRAPH_VERSION:
            raise ValueError("policy requires frozen features-v1 and graph-v1")
        if not math.isfinite(self.verify_threshold) or not math.isfinite(self.hold_threshold):
            raise ValueError("policy thresholds must be finite")
        if self.verify_threshold > self.hold_threshold:
            raise ValueError("verify_threshold must be <= hold_threshold")
        if (
            self.policy_version == POLICY_V2_VERSION
            and self.verify_threshold >= self.hold_threshold
        ):
            raise ValueError("risk-policy-v2 requires verify_threshold < hold_threshold")
        required = {PolicyAction.ESCALATE, PolicyAction.RECOMMEND_BLOCK}
        if not required.issubset(self.human_review_actions):
            raise ValueError("ESCALATE and RECOMMEND_BLOCK must require human review")
        return self

    def stable_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class OperatingConstraints(ConfigModel):
    assumptions_label: str
    minimum_abuse_intervention_recall: float = Field(ge=0, le=1)
    maximum_legitimate_intervention_rate: float = Field(ge=0, le=1)
    maximum_legitimate_severe_intervention_rate: float = Field(ge=0, le=1)
    maximum_total_human_review_rate: float = Field(ge=0, le=1)
    maximum_any_legitimate_persona_severe_intervention_rate: float = Field(ge=0, le=1)

    def stable_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def policy_path(version: str) -> Path:
    if version not in {POLICY_V1_VERSION, POLICY_V2_VERSION}:
        raise ValueError(f"unsupported policy version: {version}")
    return POLICY_DIRECTORY / f"{version}.yaml"


def _policy_document(path: Path) -> dict[str, object]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("policy config must be a mapping")
    return raw


def load_policy_config(path: Path | None = None, *, version: str | None = None) -> PolicyConfig:
    selected_path = path or (policy_path(version) if version else DEFAULT_POLICY_PATH)
    raw = _policy_document(selected_path)
    raw.pop("operating_constraints", None)
    return PolicyConfig.model_validate(raw)


def load_operating_constraints(path: Path | None = None) -> OperatingConstraints:
    selected_path = path or policy_path(POLICY_V2_VERSION)
    raw = _policy_document(selected_path)
    constraints = raw.get("operating_constraints")
    if constraints is None:
        raise ValueError("policy config has no operating_constraints")
    return OperatingConstraints.model_validate(constraints)
