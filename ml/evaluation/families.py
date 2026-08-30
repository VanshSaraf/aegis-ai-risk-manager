from collections import defaultdict
from typing import Any

import numpy as np
from sklearn.metrics import roc_auc_score

from ml.evaluation.metrics import binary_metrics
from ml.training.config import TrainingConfig
from ml.training.dataset import AssembledDataset
from ml.training.splitting import SplitResult
from ml.training.train import train_lightgbm_variant
from packages.graph_engine.registry import GRAPH_METRIC_NAMES
from packages.risk_engine.features.registry import FEATURE_NAMES


def feature_family_columns() -> dict[str, tuple[str, ...]]:
    transaction = FEATURE_NAMES[:6]
    relationship = FEATURE_NAMES[-6:]
    customer = (
        tuple(name for name in FEATURE_NAMES if name.startswith("customer_"))
        + tuple(name for name in FEATURE_NAMES if name.startswith("is_new_"))
        + ("amount_vs_customer_mean", "amount_zscore_customer")
    )
    device = tuple(name for name in FEATURE_NAMES if name.startswith("device_"))
    network = tuple(name for name in FEATURE_NAMES if name.startswith("ip_"))
    instrument = tuple(name for name in FEATURE_NAMES if name.startswith("instrument_"))
    address = tuple(name for name in FEATURE_NAMES if name.startswith("address_"))
    assigned = set(transaction + customer + device + network + instrument + address + relationship)
    if assigned != set(FEATURE_NAMES):
        raise RuntimeError(f"unassigned features-v1 columns: {set(FEATURE_NAMES) - assigned}")
    return {
        "transaction_context": transaction,
        "customer_behavior": customer,
        "device_velocity": device,
        "ip_network_velocity": network,
        "instrument_velocity": instrument,
        "address_behavior": address,
        "historical_relationships": relationship,
        "graph_v1": GRAPH_METRIC_NAMES,
    }


def diagnostic_feature_sets() -> dict[str, tuple[str, ...]]:
    families = feature_family_columns()
    transaction = families["transaction_context"]
    customer = families["customer_behavior"]
    non_relationship = FEATURE_NAMES[:-6]
    sets = {
        "transaction_context_only": transaction,
        "transaction_plus_customer": transaction + customer,
        "non_relationship_features_v1": non_relationship,
        "full_features_v1": FEATURE_NAMES,
        "graph_v1": GRAPH_METRIC_NAMES,
        "combined_77": FEATURE_NAMES + GRAPH_METRIC_NAMES,
    }
    combined = FEATURE_NAMES + GRAPH_METRIC_NAMES
    for family, names in families.items():
        removed = set(names)
        sets[f"combined_without_{family}"] = tuple(name for name in combined if name not in removed)
    return sets


def _matrix_columns(dataset: AssembledDataset, names: tuple[str, ...]) -> np.ndarray:
    positions = {name: index for index, name in enumerate(dataset.feature_names)}
    return dataset.X[:, [positions[name] for name in names]]


def _distribution(values: np.ndarray) -> dict[str, float | int]:
    return {
        "count": len(values),
        "mean": float(np.mean(values)),
        "p50": float(np.quantile(values, 0.5)),
        "p90": float(np.quantile(values, 0.9)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "max": float(np.max(values)),
    }


def univariate_diagnostics(dataset: AssembledDataset) -> list[dict[str, float | str]]:
    output: list[dict[str, float | str]] = []
    y = dataset.y
    for index, name in enumerate(dataset.feature_names):
        values = dataset.X[:, index]
        auc = float(roc_auc_score(y, values)) if len(np.unique(values)) > 1 else 0.5
        output.append({"feature": name, "directional_roc_auc": max(auc, 1.0 - auc)})
    return sorted(
        output, key=lambda item: (-float(item["directional_roc_auc"]), str(item["feature"]))
    )


def sliced_distributions(
    dataset: AssembledDataset, feature_names: tuple[str, ...]
) -> dict[str, dict[str, dict[str, float | int]]]:
    positions = {name: index for index, name in enumerate(dataset.feature_names)}
    groups: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(dataset.metadata):
        groups["label:coordinated_abuse" if item.label else "label:legitimate"].append(index)
        if item.persona:
            groups[f"persona:{item.persona}"].append(index)
        if item.label:
            groups[f"scenario:{item.scenario}"].append(index)
    return {
        feature: {
            group: _distribution(dataset.X[indices, positions[feature]])
            for group, indices in sorted(groups.items())
        }
        for feature in feature_names
    }


def run_family_diagnostics(
    dataset: AssembledDataset,
    split: SplitResult,
    config: TrainingConfig,
    *,
    include_leave_one_family_out: bool,
) -> dict[str, Any]:
    sets = diagnostic_feature_sets()
    if not include_leave_one_family_out:
        keep = {
            "transaction_context_only",
            "transaction_plus_customer",
            "non_relationship_features_v1",
            "full_features_v1",
            "graph_v1",
            "combined_77",
        }
        sets = {name: features for name, features in sets.items() if name in keep}
    results: dict[str, object] = {}
    importances: dict[str, list[dict[str, float | str]]] = {}
    for name, feature_names in sets.items():
        matrix = _matrix_columns(dataset, feature_names)
        trained = train_lightgbm_variant(
            name,
            feature_names,
            matrix[split.train],
            dataset.y[split.train],
            matrix[split.validation],
            dataset.y[split.validation],
            config,
        )
        test_scores = np.asarray(trained.model.booster_.predict(matrix[split.test]))
        results[name] = {
            "feature_count": len(feature_names),
            "selected_candidate": trained.selected_candidate,
            "selected_threshold": trained.selected_threshold,
            "validation": trained.validation_metrics,
            "test": binary_metrics(dataset.y[split.test], test_scores, trained.selected_threshold),
        }
        gains = trained.model.booster_.feature_importance(importance_type="gain")
        importances[name] = sorted(
            [
                {"feature": feature, "gain": float(gain)}
                for feature, gain in zip(feature_names, gains, strict=True)
            ],
            key=lambda item: (-float(item["gain"]), str(item["feature"])),
        )[:20]
    univariate = univariate_diagnostics(dataset)
    strongest = tuple(str(item["feature"]) for item in univariate[:10])
    inspected = tuple(
        dict.fromkeys(
            strongest
            + (
                "ip_txn_count_10m",
                "device_txn_count_10m",
                "device_failed_txn_count_10m",
                "ip_failed_txn_count_10m",
                "account_age_hours",
                "historical_customers_on_current_device",
                "historical_instruments_on_current_device",
                "historical_customers_on_current_ip",
            )
        )
    )
    return {
        "purpose": "retrospective development diagnostic; not a new sealed benchmark",
        "family_definitions": {
            name: list(values) for name, values in feature_family_columns().items()
        },
        "models": results,
        "feature_importance": importances,
        "univariate": univariate,
        "distributions": sliced_distributions(dataset, inspected),
    }
