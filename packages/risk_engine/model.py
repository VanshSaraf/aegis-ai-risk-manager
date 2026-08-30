import json
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np

from packages.graph_engine.registry import GRAPH_METRIC_NAMES, GRAPH_VERSION
from packages.risk_engine.features.registry import FEATURE_NAMES, FEATURE_VERSION


@dataclass(frozen=True, slots=True)
class ModelScore:
    model_version: str
    score: float


class RiskModel:
    """Portable score-only model boundary; it makes no policy or fraud decision."""

    def __init__(self, model: lgb.Booster, metadata: dict[str, object]) -> None:
        self._model = model
        self.metadata = metadata
        self.feature_order = tuple(str(item) for item in metadata["feature_order"])

    @classmethod
    def load(cls, artifact_directory: Path) -> "RiskModel":
        metadata = json.loads((artifact_directory / "metadata.json").read_text(encoding="utf-8"))
        expected = FEATURE_NAMES + GRAPH_METRIC_NAMES
        if metadata.get("feature_version") != FEATURE_VERSION:
            raise ValueError("model artifact feature schema version mismatch")
        if metadata.get("graph_version") != GRAPH_VERSION:
            raise ValueError("model artifact graph schema version mismatch")
        if tuple(metadata.get("feature_order", ())) != expected:
            raise ValueError("model artifact feature names/order mismatch")
        if metadata.get("feature_count") != len(expected):
            raise ValueError("model artifact feature count mismatch")
        model = lgb.Booster(model_file=str(artifact_directory / "model.txt"))
        if tuple(model.feature_name()) != expected:
            raise ValueError("native model feature names/order mismatch")
        return cls(model, metadata)

    def predict(
        self,
        feature_values: dict[str, float | int | bool],
        graph_metrics: dict[str, float | int | bool],
    ) -> ModelScore:
        supplied = set(feature_values) | set(graph_metrics)
        if supplied != set(self.feature_order):
            missing = set(self.feature_order) - supplied
            unexpected = supplied - set(self.feature_order)
            raise ValueError(
                f"model input schema mismatch; missing={missing}, unexpected={unexpected}"
            )
        values = {**feature_values, **graph_metrics}
        matrix = np.asarray([[float(values[name]) for name in self.feature_order]])
        score = float(self._model.predict(matrix)[0])
        return ModelScore(str(self.metadata["model_version"]), score)

    def predict_matrix(self, matrix: np.ndarray, feature_order: tuple[str, ...]) -> np.ndarray:
        if feature_order != self.feature_order or matrix.shape[1] != len(self.feature_order):
            raise ValueError("model input feature names/order mismatch")
        return np.asarray(self._model.predict(matrix), dtype=np.float64)
