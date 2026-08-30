import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SplitRatios(StrictModel):
    train: float = Field(gt=0, lt=1)
    validation: float = Field(gt=0, lt=1)
    test: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def sum_to_one(self) -> "SplitRatios":
        if abs(self.train + self.validation + self.test - 1.0) > 1e-9:
            raise ValueError("split ratios must sum to one")
        return self


class LightGBMCandidate(StrictModel):
    name: str
    num_leaves: int = Field(ge=2)
    min_child_samples: int = Field(ge=1)
    learning_rate: float = Field(gt=0)
    n_estimators: int = Field(ge=1)
    colsample_bytree: float = Field(gt=0, le=1)
    reg_lambda: float = Field(ge=0)
    class_weight: Literal["balanced"] | None = None


class TrainingConfig(StrictModel):
    model_version: str
    benchmark_seed: int
    transaction_count: int = Field(ge=50)
    abuse_prevalence: float = Field(gt=0, lt=1)
    feature_version: str
    graph_version: str
    generation_config_path: str | None = None
    split_ratios: SplitRatios
    random_seed: int
    early_stopping_rounds: int = Field(ge=1)
    threshold_selection_objective: Literal["validation_f1"]
    lightgbm_candidates: tuple[LightGBMCandidate, ...] = Field(min_length=1, max_length=10)

    def stable_hash(self) -> str:
        values = self.model_dump(mode="json")
        if self.generation_config_path is None:
            values.pop("generation_config_path")
        payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


def load_training_config(path: Path) -> TrainingConfig:
    return TrainingConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
