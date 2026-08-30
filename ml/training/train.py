import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.metrics import average_precision_score

from ml.evaluation.metrics import binary_metrics, select_validation_f1_threshold
from ml.training.config import TrainingConfig


@dataclass(slots=True)
class TrainedVariant:
    name: str
    feature_names: tuple[str, ...]
    model: lgb.LGBMClassifier
    selected_candidate: dict[str, Any]
    selected_threshold: float
    validation_scores: np.ndarray
    validation_metrics: dict[str, object]
    validation_metrics_at_0_5: dict[str, object]
    candidate_results: list[dict[str, object]]
    training_seconds: float


def _candidate_params(config: TrainingConfig, candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        **candidate,
        "objective": "binary",
        "random_state": config.random_seed,
        "deterministic": True,
        "force_col_wise": True,
        "n_jobs": 1,
        "verbosity": -1,
        "data_random_seed": config.random_seed,
        "feature_fraction_seed": config.random_seed,
        "bagging_seed": config.random_seed,
    }


def train_lightgbm_variant(
    name: str,
    feature_names: tuple[str, ...],
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_validation: np.ndarray,
    y_validation: np.ndarray,
    config: TrainingConfig,
) -> TrainedVariant:
    started = time.perf_counter()
    candidates: list[tuple[float, str, lgb.LGBMClassifier, np.ndarray, dict[str, Any]]] = []
    candidate_results: list[dict[str, object]] = []
    for candidate_model in config.lightgbm_candidates:
        candidate = candidate_model.model_dump(exclude={"name"}, exclude_none=True)
        model = lgb.LGBMClassifier(**_candidate_params(config, candidate))
        model.fit(
            X_train,
            y_train,
            eval_X=X_validation,
            eval_y=y_validation,
            eval_metric="average_precision",
            callbacks=[lgb.early_stopping(config.early_stopping_rounds, verbose=False)],
            feature_name=list(feature_names),
        )
        scores = np.asarray(model.booster_.predict(X_validation), dtype=np.float64)
        pr_auc = float(average_precision_score(y_validation, scores))
        result = {
            "name": candidate_model.name,
            "validation_pr_auc": pr_auc,
            "best_iteration": int(model.best_iteration_),
            "parameters": candidate,
        }
        candidate_results.append(result)
        candidates.append((pr_auc, candidate_model.name, model, scores, result))
    _, _, selected, validation_scores, selected_result = max(
        candidates, key=lambda item: (item[0], item[1])
    )
    threshold = select_validation_f1_threshold(y_validation, validation_scores)
    return TrainedVariant(
        name=name,
        feature_names=feature_names,
        model=selected,
        selected_candidate=selected_result,
        selected_threshold=threshold,
        validation_scores=validation_scores,
        validation_metrics=binary_metrics(y_validation, validation_scores, threshold),
        validation_metrics_at_0_5=binary_metrics(y_validation, validation_scores, 0.5),
        candidate_results=candidate_results,
        training_seconds=time.perf_counter() - started,
    )


def dummy_prior_baseline(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_evaluation: np.ndarray,
    y_evaluation: np.ndarray,
) -> dict[str, object]:
    model = DummyClassifier(strategy="prior").fit(X_train, y_train)
    scores = model.predict_proba(X_evaluation)[:, 1]
    threshold = select_validation_f1_threshold(y_evaluation, scores)
    return {
        "threshold": threshold,
        "scores": scores,
        "metrics": binary_metrics(y_evaluation, scores, threshold),
    }


def prediction_digest(scores: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(scores, dtype="<f8").tobytes()).hexdigest()


def model_config_hash(variant: TrainedVariant, config: TrainingConfig) -> str:
    payload = {
        "training_config_hash": config.stable_hash(),
        "variant": variant.name,
        "candidate": variant.selected_candidate,
        "feature_names": variant.feature_names,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
