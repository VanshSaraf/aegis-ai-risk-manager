import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.api.app.core.enums import ScenarioType

DEFAULT_CONFIG_PATH = Path(__file__).parents[2] / "configs" / "scenarios" / "default.yaml"


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetConfig(ConfigModel):
    seed: int = 42017
    transaction_count: int = Field(default=10_000, ge=50, le=1_000_000)
    start_time: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    simulation_days: int = Field(default=30, ge=1, le=3650)

    @field_validator("start_time")
    @classmethod
    def start_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_time must be timezone-aware")
        return value.astimezone(UTC)


class AbuseConfig(ConfigModel):
    prevalence: float = Field(default=0.07, ge=0, le=1)
    prevalence_tolerance: float = Field(default=0.01, ge=0, le=0.25)
    scenario_weights: dict[ScenarioType, float]

    @model_validator(mode="after")
    def valid_scenario_weights(self) -> "AbuseConfig":
        allowed = {
            ScenarioType.CARD_TESTING,
            ScenarioType.ACCOUNT_FARM,
            ScenarioType.IDENTITY_ROTATION,
            ScenarioType.COLLUSIVE_RING,
        }
        if set(self.scenario_weights) != allowed:
            raise ValueError("scenario_weights must contain all four abuse scenarios")
        if abs(sum(self.scenario_weights.values()) - 1.0) > 1e-9:
            raise ValueError("scenario_weights must sum to 1")
        if any(weight < 0 for weight in self.scenario_weights.values()):
            raise ValueError("scenario weights cannot be negative")
        return self


class BehaviorConfig(ConfigModel):
    amount_min_paise: int = Field(ge=1)
    amount_max_paise: int = Field(gt=1)
    low_value_paise: int = Field(ge=1)
    high_value_paise: int = Field(ge=1)
    amount_lognormal_sigma: float = Field(gt=0, le=3)
    merchant_median_paise: dict[str, int]
    legitimate_failure_rate: float = Field(ge=0, le=1)
    abuse_failure_rate: float = Field(ge=0, le=1)
    new_account_fraction: float = Field(ge=0, le=1)
    abuse_burst_spacing_seconds: int = Field(ge=1, le=3600)

    @model_validator(mode="after")
    def valid_amount_bounds(self) -> "BehaviorConfig":
        if not (
            self.amount_min_paise
            < self.low_value_paise
            < self.high_value_paise
            < self.amount_max_paise
        ):
            raise ValueError("amount thresholds must be strictly ordered")
        expected_categories = {
            "ECOMMERCE",
            "FOOD",
            "TRAVEL",
            "ELECTRONICS",
            "FASHION",
            "GAMING",
            "SUBSCRIPTION",
            "EDUCATION",
        }
        if set(self.merchant_median_paise) != expected_categories:
            raise ValueError("merchant_median_paise must cover every merchant category")
        if any(value <= 0 for value in self.merchant_median_paise.values()):
            raise ValueError("merchant median amounts must be positive")
        return self


class PopulationConfig(ConfigModel):
    transactions_per_customer: int = Field(default=8, ge=1, le=1000)
    merchant_count: int = Field(default=32, ge=8, le=10_000)


class GenerationConfig(ConfigModel):
    generator_version: str = Field(default="synthetic-v1", min_length=1, max_length=100)
    dataset: DatasetConfig
    abuse: AbuseConfig
    legitimate_persona_weights: dict[str, float]
    behavior: BehaviorConfig
    population: PopulationConfig

    @model_validator(mode="after")
    def valid_persona_weights(self) -> "GenerationConfig":
        expected = {
            "STANDARD_RETAIL",
            "POWER_SHOPPER",
            "FAMILY_HOUSEHOLD",
            "CORPORATE_OR_CAMPUS_NETWORK",
            "TRAVELLER",
        }
        if set(self.legitimate_persona_weights) != expected:
            raise ValueError("legitimate_persona_weights must contain every persona")
        if abs(sum(self.legitimate_persona_weights.values()) - 1.0) > 1e-9:
            raise ValueError("legitimate persona weights must sum to 1")
        return self

    def canonical_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def config_hash(self) -> str:
        canonical = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def load_generation_config(path: Path | None = None) -> GenerationConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    return GenerationConfig.model_validate(data)
