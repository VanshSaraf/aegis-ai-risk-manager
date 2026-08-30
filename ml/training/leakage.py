from dataclasses import dataclass

import numpy as np
from sklearn.metrics import roc_auc_score

from ml.training.dataset import COMBINED_FEATURE_NAMES, FORBIDDEN_INPUT_TERMS


@dataclass(frozen=True, slots=True)
class LeakageAudit:
    feature_count: int
    strongest_feature: str
    strongest_univariate_auc: float
    suspicious_features: tuple[str, ...]
    constant_features: tuple[str, ...]
    near_constant_features: tuple[str, ...]
    non_finite_count: int
    exact_label_aliases: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_count": self.feature_count,
            "strongest_feature": self.strongest_feature,
            "strongest_univariate_auc": self.strongest_univariate_auc,
            "suspicious_features": list(self.suspicious_features),
            "constant_features": list(self.constant_features),
            "near_constant_features": list(self.near_constant_features),
            "non_finite_count": self.non_finite_count,
            "exact_label_aliases": list(self.exact_label_aliases),
            "forbidden_column_check": "passed",
            "registered_schema_check": "passed",
        }


def audit_model_matrix(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: tuple[str, ...],
    *,
    expected_names: tuple[str, ...] = COMBINED_FEATURE_NAMES,
) -> LeakageAudit:
    if feature_names != expected_names:
        raise ValueError("model input must exactly match the registered predictive schema")
    forbidden = [
        name
        for name in feature_names
        if any(term in name.lower() for term in FORBIDDEN_INPUT_TERMS)
    ]
    if forbidden:
        raise ValueError(f"forbidden predictive columns: {forbidden}")
    if X.shape != (len(y), len(feature_names)):
        raise ValueError("matrix dimensions do not match labels and feature schema")
    non_finite = int((~np.isfinite(X)).sum())
    if non_finite:
        raise ValueError(f"model matrix contains {non_finite} non-finite values")
    aucs: dict[str, float] = {}
    constants: list[str] = []
    near_constants: list[str] = []
    aliases: list[str] = []
    for index, name in enumerate(feature_names):
        column = X[:, index]
        values, counts = np.unique(column, return_counts=True)
        if len(values) == 1:
            constants.append(name)
            aucs[name] = 0.5
        else:
            auc = float(roc_auc_score(y, column))
            aucs[name] = max(auc, 1.0 - auc)
            if counts.max() / len(column) >= 0.999:
                near_constants.append(name)
        if np.array_equal(column, y) or np.array_equal(column, 1 - y):
            aliases.append(name)
    if aliases:
        raise ValueError(f"exact label aliases found: {aliases}")
    strongest = max(aucs, key=aucs.__getitem__)
    return LeakageAudit(
        len(feature_names),
        strongest,
        aucs[strongest],
        tuple(sorted(name for name, auc in aucs.items() if auc >= 0.995)),
        tuple(constants),
        tuple(near_constants),
        non_finite,
        tuple(aliases),
    )
