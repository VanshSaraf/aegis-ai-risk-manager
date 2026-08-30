import asyncio
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np

from ml.evaluation.diagnostics import graph_cluster_ring_matching
from ml.evaluation.families import run_family_diagnostics
from ml.evaluation.metrics import (
    binary_metrics,
    persona_false_positives,
    scenario_recall,
)
from ml.training.artifacts import write_json
from ml.training.config import load_training_config
from ml.training.dataset import COMBINED_FEATURE_NAMES, assemble_benchmark, schema_hashes
from ml.training.leakage import audit_model_matrix
from ml.training.splitting import manifest_hash, split_chronologically
from ml.training.train import (
    TrainedVariant,
    dummy_prior_baseline,
    model_config_hash,
    prediction_digest,
    train_lightgbm_variant,
)
from packages.graph_engine.registry import GRAPH_METRIC_NAMES
from packages.risk_engine.features.registry import FEATURE_NAMES
from packages.risk_engine.model import RiskModel


def _evaluate_variant(
    variant: TrainedVariant, X: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, dict[str, object]]:
    scores = np.asarray(variant.model.booster_.predict(X), dtype=np.float64)
    return scores, {
        "selected_threshold": binary_metrics(y, scores, variant.selected_threshold),
        "threshold_0_5": binary_metrics(y, scores, 0.5),
    }


def _variant_artifact(variant: TrainedVariant) -> dict[str, object]:
    return {
        "input_count": len(variant.feature_names),
        "selected_candidate": variant.selected_candidate,
        "selected_threshold": variant.selected_threshold,
        "threshold_selection_objective": "validation_f1",
        "validation_metrics": variant.validation_metrics,
        "validation_metrics_at_0_5": variant.validation_metrics_at_0_5,
        "candidate_results": variant.candidate_results,
        "training_seconds": variant.training_seconds,
        "validation_prediction_digest": prediction_digest(variant.validation_scores),
    }


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


async def run_benchmark(
    config_path: Path,
    artifact_directory: Path,
    *,
    evaluate_test: bool,
    transaction_count_override: int | None = None,
) -> dict[str, object]:
    repository_root = config_path.parents[2]
    config = load_training_config(config_path)
    if transaction_count_override is not None:
        config = config.model_copy(update={"transaction_count": transaction_count_override})
    dataset = await assemble_benchmark(config)
    split = split_chronologically(
        dataset.metadata,
        config.split_ratios,
        require_all_scenarios=config.transaction_count >= 20_000,
    )
    split.manifest.update(
        {
            "dataset_version": dataset.manifest.dataset_version,
            "benchmark_seed": config.benchmark_seed,
            "dataset_config_hash": dataset.synthetic_dataset.config_hash,
            "feature_version": config.feature_version,
            "graph_version": config.graph_version,
        }
    )
    hashes = schema_hashes(repository_root)
    split_hash = manifest_hash(split.manifest)
    audit = audit_model_matrix(
        dataset.X[split.train], dataset.y[split.train], dataset.feature_names
    )

    slices = {
        "tabular_lightgbm": (slice(0, len(FEATURE_NAMES)), FEATURE_NAMES),
        "graph_lightgbm": (slice(len(FEATURE_NAMES), None), GRAPH_METRIC_NAMES),
        "combined_lightgbm": (slice(None), COMBINED_FEATURE_NAMES),
    }
    variants: dict[str, TrainedVariant] = {}
    for name, (column_slice, names) in slices.items():
        variants[name] = train_lightgbm_variant(
            name,
            names,
            dataset.X[split.train, column_slice],
            dataset.y[split.train],
            dataset.X[split.validation, column_slice],
            dataset.y[split.validation],
            config,
        )
    dummy = dummy_prior_baseline(
        dataset.X[split.train, :1],
        dataset.y[split.train],
        dataset.X[split.validation, :1],
        dataset.y[split.validation],
    )
    validation_metrics: dict[str, object] = {
        name: _variant_artifact(variant) for name, variant in variants.items()
    }
    validation_metrics["deterministic_graph_baseline"] = binary_metrics(
        dataset.y[split.validation],
        dataset.graph_baseline[split.validation].astype(float),
        0.5,
    )
    validation_metrics["dummy_class_prior"] = dummy["metrics"]

    combined = variants["combined_lightgbm"]
    artifact_directory.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    combined.model.booster_.save_model(str(artifact_directory / "model.txt"))
    trained_at = datetime.now(UTC).isoformat()
    metadata: dict[str, object] = {
        "model_version": config.model_version,
        "model_type": "LightGBM binary classifier",
        "model_output_semantics": "uncalibrated model_score; not a fraud probability",
        "trained_at": trained_at,
        "benchmark_dataset_version": dataset.manifest.dataset_version,
        "benchmark_seed": config.benchmark_seed,
        "feature_version": config.feature_version,
        "graph_version": config.graph_version,
        "feature_count": len(COMBINED_FEATURE_NAMES),
        "feature_order": list(COMBINED_FEATURE_NAMES),
        "training_config_hash": config.stable_hash(),
        "model_config_hash": model_config_hash(combined, config),
        "split_manifest_hash": split_hash,
        **hashes,
        "selected_threshold": combined.selected_threshold,
        "threshold_selection_method": config.threshold_selection_objective,
        "lightgbm_version": lgb.__version__,
        "python_version": platform.python_version(),
        "validation_metrics": combined.validation_metrics,
        "test_evaluated_at": None,
        "test_metrics": None,
    }
    write_json(artifact_directory / "metadata.json", metadata)

    loaded = RiskModel.load(artifact_directory)
    validation_matrix = dataset.X[split.validation]
    before = np.asarray(combined.model.booster_.predict(validation_matrix), dtype=np.float64)
    after = loaded.predict_matrix(validation_matrix, COMBINED_FEATURE_NAMES)
    reload_max_delta = float(np.max(np.abs(before - after)))
    if reload_max_delta > 1e-12:
        raise ValueError(f"model reload prediction mismatch: {reload_max_delta}")

    reproducibility_started = time.perf_counter()
    reproduction = train_lightgbm_variant(
        "combined_lightgbm",
        COMBINED_FEATURE_NAMES,
        dataset.X[split.train],
        dataset.y[split.train],
        validation_matrix,
        dataset.y[split.validation],
        config,
    )
    reproducibility_max_delta = float(
        np.max(np.abs(combined.validation_scores - reproduction.validation_scores))
    )
    if reproducibility_max_delta > 1e-12:
        raise ValueError(f"deterministic training prediction mismatch: {reproducibility_max_delta}")
    reproducibility_seconds = time.perf_counter() - reproducibility_started

    test_metrics: dict[str, object] | None = None
    diagnostics: dict[str, object] | None = None
    family_ablation: dict[str, object] | None = None
    if evaluate_test:
        test_metrics = {}
        test_scores: dict[str, np.ndarray] = {}
        for name, variant in variants.items():
            column_slice = slices[name][0]
            scores, metrics = _evaluate_variant(
                variant, dataset.X[split.test, column_slice], dataset.y[split.test]
            )
            test_scores[name] = scores
            test_metrics[name] = metrics
        test_metrics["deterministic_graph_baseline"] = binary_metrics(
            dataset.y[split.test], dataset.graph_baseline[split.test].astype(float), 0.5
        )
        dummy_test_scores = np.full(len(split.test), dataset.y[split.train].mean())
        test_metrics["dummy_class_prior"] = binary_metrics(
            dataset.y[split.test], dummy_test_scores, float(dummy["threshold"])
        )
        test_metadata = [dataset.metadata[int(index)] for index in split.test]
        diagnostics = {
            "scenario_recall": {
                name: scenario_recall(test_metadata, scores, variants[name].selected_threshold)
                for name, scores in test_scores.items()
            },
            "persona_false_positives": {
                name: persona_false_positives(
                    test_metadata, scores, variants[name].selected_threshold
                )
                for name, scores in test_scores.items()
            },
            "graph_cluster_matching": graph_cluster_ring_matching(
                dataset, [int(index) for index in split.test]
            ),
        }
        if config.model_version == "risk-lgbm-v2":
            family_ablation = run_family_diagnostics(
                dataset,
                split,
                config,
                include_leave_one_family_out=False,
            )
        metadata["test_evaluated_at"] = datetime.now(UTC).isoformat()
        metadata["test_metrics"] = test_metrics["combined_lightgbm"]["selected_threshold"]
        write_json(artifact_directory / "metadata.json", metadata)

    report: dict[str, object] = {
        "dataset": dataset.manifest.model_dump(mode="json"),
        "split": split.manifest,
        "abuse_infrastructure_overlap_audit": {
            "cross_ring_shared_entity_count": len(split.cross_ring_shared_entities),
            "shared_entities": {
                key: list(value) for key, value in split.cross_ring_shared_entities.items()
            },
        },
        "model_inputs": {"tabular": 52, "graph": 25, "combined": 77},
        "leakage_audit": audit.as_dict(),
        "validation": validation_metrics,
        "test": test_metrics,
        "diagnostics": diagnostics,
        "family_ablation": family_ablation,
        "runtimes": {
            **dataset.runtimes,
            "training_seconds": sum(item.training_seconds for item in variants.values()),
            "reproducibility_check_seconds": reproducibility_seconds,
        },
        "artifact_reload": {
            "validation_samples": len(split.validation),
            "maximum_absolute_prediction_delta": reload_max_delta,
            "passed": True,
        },
        "reproducibility": {
            "maximum_absolute_prediction_delta": reproducibility_max_delta,
            "prediction_digest": prediction_digest(combined.validation_scores),
            "same_environment_passed": True,
        },
        "traceability": {
            "training_config_hash": config.stable_hash(),
            "split_manifest_hash": split_hash,
            **hashes,
        },
    }
    write_json(artifact_directory / "training_config.json", config.model_dump(mode="json"))
    write_json(artifact_directory / "feature_order.json", list(COMBINED_FEATURE_NAMES))
    write_json(artifact_directory / "split_manifest.json", split.manifest)
    write_json(artifact_directory / "validation_metrics.json", validation_metrics)
    write_json(artifact_directory / "test_metrics.json", test_metrics)
    write_json(
        artifact_directory / "ablation.json",
        {
            "validation": validation_metrics,
            "test": test_metrics,
            "diagnostics": diagnostics,
            "family_ablation": family_ablation,
        },
    )
    write_json(artifact_directory / "leakage_audit.json", audit.as_dict())
    write_json(artifact_directory / "benchmark.json", _json_clone(report))
    return report


def run(
    config_path: Path,
    artifact_directory: Path,
    *,
    evaluate_test: bool,
    transaction_count_override: int | None = None,
) -> dict[str, object]:
    return asyncio.run(
        run_benchmark(
            config_path,
            artifact_directory,
            evaluate_test=evaluate_test,
            transaction_count_override=transaction_count_override,
        )
    )
