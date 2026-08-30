from collections import Counter
from collections.abc import Iterable

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
)

from ml.training.dataset import EvaluationMetadata


def select_validation_f1_threshold(y_true: np.ndarray, scores: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    if not len(thresholds):
        return 0.5
    denominators = precision[:-1] + recall[:-1]
    f1 = np.divide(
        2 * precision[:-1] * recall[:-1],
        denominators,
        out=np.zeros_like(denominators),
        where=denominators != 0,
    )
    best_f1 = f1.max()
    return float(thresholds[np.flatnonzero(f1 == best_f1)[-1]])


def binary_metrics(y_true: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, object]:
    predictions = (scores >= threshold).astype(np.int8)
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "pr_auc": float(average_precision_score(y_true, scores)),
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        "true_positive": int(tp),
        "false_positive": int(fp),
        "true_negative": int(tn),
        "false_negative": int(fn),
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
        "false_negative_rate": float(fn / (fn + tp)) if fn + tp else 0.0,
        "accuracy": float((tp + tn) / len(y_true)),
    }


def scenario_recall(
    metadata: Iterable[EvaluationMetadata], scores: np.ndarray, threshold: float
) -> dict[str, dict[str, float | int]]:
    items = list(metadata)
    output: dict[str, dict[str, float | int]] = {}
    for scenario in sorted({item.scenario for item in items if item.label}):
        indices = [
            index for index, item in enumerate(items) if item.label and item.scenario == scenario
        ]
        caught = sum(scores[index] >= threshold for index in indices)
        output[scenario] = {
            "positive_transactions": len(indices),
            "true_positive": int(caught),
            "recall": float(caught / len(indices)) if indices else 0.0,
        }
    return output


def persona_false_positives(
    metadata: Iterable[EvaluationMetadata], scores: np.ndarray, threshold: float
) -> dict[str, dict[str, float | int]]:
    items = list(metadata)
    output: dict[str, dict[str, float | int]] = {}
    for persona in sorted({item.persona for item in items if not item.label and item.persona}):
        indices = [
            index for index, item in enumerate(items) if not item.label and item.persona == persona
        ]
        false_positives = sum(scores[index] >= threshold for index in indices)
        output[persona] = {
            "legitimate_transactions": len(indices),
            "false_positive": int(false_positives),
            "false_positive_rate": float(false_positives / len(indices)) if indices else 0.0,
        }
    return output


def class_counts(y: np.ndarray) -> dict[str, int]:
    counts = Counter("abuse" if value else "legitimate" for value in y)
    return dict(sorted(counts.items()))
