import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, confusion_matrix, roc_auc_score

from ml.training.artifacts import write_json
from ml.training.config import load_training_config
from ml.training.dataset import assemble_benchmark
from ml.training.splitting import manifest_hash, split_chronologically
from packages.policy_engine.backtest import BacktestExample, evaluate_policy
from packages.policy_engine.config import (
    POLICY_V1_VERSION,
    POLICY_V2_VERSION,
    load_operating_constraints,
    load_policy_config,
)
from packages.policy_engine.costs import load_cost_profile
from packages.policy_engine.optimizer import optimize_thresholds
from packages.risk_engine.model import RiskModel
from scripts.build_policy_artifacts import _examples, _select

ROOT = Path(__file__).parents[1]
MODEL_DIRECTORY = ROOT / "ml/artifacts/model-v2"
POLICY_V2_DIRECTORY = ROOT / "ml/artifacts/policy-v2"
EXTERNAL_SEED = 91573
EXTERNAL_TRANSACTION_COUNT = 50_000
EXTERNAL_ABUSE_PREVALENCE = 0.07


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_external_seed_unseen(output: Path) -> None:
    forbidden_names = [
        path
        for root in (ROOT / "ml/datasets/generated", output)
        if root.exists()
        for path in root.rglob(f"*{EXTERNAL_SEED}*")
    ]
    forbidden_outputs = [
        output / name
        for name in (
            "external_metrics.json",
            "policy_comparison.json",
            "persona_external.json",
            "scenario_external.json",
        )
        if (output / name).exists()
    ]
    if forbidden_names or forbidden_outputs:
        paths = sorted(str(path) for path in forbidden_names + forbidden_outputs)
        raise RuntimeError(f"external seed must be unseen before policy-v2 freeze: {paths}")


def _verify_frozen_split(dataset: Any, training: Any) -> Any:
    split = split_chronologically(dataset.metadata, training.split_ratios)
    split.manifest.update(
        {
            "dataset_version": dataset.manifest.dataset_version,
            "benchmark_seed": training.benchmark_seed,
            "dataset_config_hash": dataset.synthetic_dataset.config_hash,
            "feature_version": training.feature_version,
            "graph_version": training.graph_version,
        }
    )
    expected = _json(MODEL_DIRECTORY / "split_manifest.json")
    if manifest_hash(split.manifest) != manifest_hash(expected):
        raise RuntimeError("reconstructed policy dataset does not match frozen model-v2 split")
    return split


async def freeze_policy(output: Path) -> dict[str, Any]:
    _assert_external_seed_unseen(output)
    training = load_training_config(ROOT / "configs/ml/model-v2.yaml")
    dataset = await assemble_benchmark(training)
    split = _verify_frozen_split(dataset, training)
    model = RiskModel.load(MODEL_DIRECTORY)
    scores = model.predict_matrix(dataset.X, dataset.feature_names)
    validation = _select(_examples(dataset, scores), split.validation)

    base = load_policy_config(version=POLICY_V2_VERSION)
    policy_v1 = load_policy_config(version=POLICY_V1_VERSION)
    constraints = load_operating_constraints()
    cost = load_cost_profile(ROOT / "configs/costs/balanced-v1.yaml")
    model_metadata = _json(MODEL_DIRECTORY / "metadata.json")
    additional = (
        float(model_metadata["selected_threshold"]),
        policy_v1.verify_threshold,
        policy_v1.hold_threshold,
    )
    optimized = optimize_thresholds(
        validation,
        base,
        cost,
        constraints=constraints,
        quantile_count=41,
        additional_thresholds=additional,
    )
    policy = optimized.policy
    metrics = optimized.validation_metrics
    if policy.verify_threshold >= policy.hold_threshold:
        raise RuntimeError("policy-v2 freeze requires verify_threshold < hold_threshold")
    if metrics["action_counts"]["VERIFY"] == 0:
        raise RuntimeError("policy-v2 freeze requires a populated validation VERIFY band")

    output.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - one-time artifact CLI
    freeze = {
        "checkpoint": "RISK-POLICY-V2 FROZEN",
        "policy_version": policy.policy_version,
        "model_version": policy.model_version,
        "feature_version": policy.feature_version,
        "graph_version": policy.graph_version,
        "source_dataset_version": dataset.manifest.dataset_version,
        "cost_profile": cost.cost_profile_version,
        "operating_constraints": constraints.model_dump(mode="json"),
        "verify_threshold": policy.verify_threshold,
        "hold_threshold": policy.hold_threshold,
        "graph_corroboration": policy.graph_corroboration.model_dump(mode="json"),
        "candidate_generation": optimized.candidate_generation,
        "candidate_threshold_count": optimized.candidate_threshold_count,
        "evaluated_pair_count": optimized.evaluated_pair_count,
        "feasible_candidate_count": optimized.feasible_candidate_count,
        "policy_config_hash": policy.stable_hash(),
        "operating_constraints_hash": constraints.stable_hash(),
        "cost_config_hash": cost.stable_hash(),
        "model_metadata_hash": model_metadata["model_config_hash"],
        "feature_schema_hash": model_metadata["feature_schema_hash"],
        "graph_schema_hash": model_metadata["graph_schema_hash"],
        "threshold_selection_data": "seed 88421 validation partition only",
        "objective": optimized.objective,
        "tie_break": optimized.tie_break,
        "external_evaluation_seed": EXTERNAL_SEED,
        "external_seed_evaluated_at_checkpoint": False,
        "frozen_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "policy.json", policy.model_dump(mode="json"))
    write_json(output / "operating_constraints.json", constraints.model_dump(mode="json"))
    write_json(output / "validation_frontier.json", list(optimized.frontier))
    write_json(output / "validation_metrics.json", metrics)
    write_json(output / "freeze.json", freeze)
    metadata = {
        "policy_version": policy.policy_version,
        "policy_config_hash": policy.stable_hash(),
        "operating_constraints_hash": constraints.stable_hash(),
        "cost_config_hash": cost.stable_hash(),
        "candidate_threshold_count": optimized.candidate_threshold_count,
        "evaluated_pair_count": optimized.evaluated_pair_count,
        "feasible_candidate_count": optimized.feasible_candidate_count,
        "rejected_by_constraint": optimized.rejected_by_constraint,
        "candidate_generation": optimized.candidate_generation,
        "pipeline_runtimes": dataset.runtimes,
        "external_evaluation": None,
    }
    write_json(output / "metadata.json", metadata)
    return {"freeze": freeze, "validation": metrics, "metadata": metadata}


def _model_diagnostic(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    predictions = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    precision = int(tp) / int(tp + fp) if tp + fp else 0.0
    recall = int(tp) / int(tp + fn) if tp + fn else 0.0
    return {
        "threshold": threshold,
        "pr_auc": float(average_precision_score(labels, scores)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "true_positive": int(tp),
        "false_positive": int(fp),
        "true_negative": int(tn),
        "false_negative": int(fn),
    }


def _dataset_summary(dataset: Any) -> dict[str, Any]:
    labels = np.asarray([item.label for item in dataset.metadata])
    subtype = Counter(item.scenario for item in dataset.metadata if item.label)
    persona = Counter(item.persona for item in dataset.metadata if not item.label and item.persona)
    rings: dict[str, set[str]] = defaultdict(set)
    for item in dataset.metadata:
        if item.label and item.ring_id:
            rings[item.scenario].add(item.ring_id)
    abuse_count = int(labels.sum())
    return {
        "dataset_version": dataset.manifest.dataset_version,
        "seed": EXTERNAL_SEED,
        "transaction_count": len(labels),
        "legitimate_count": len(labels) - abuse_count,
        "abuse_count": abuse_count,
        "abuse_prevalence": abuse_count / len(labels),
        "ring_count": sum(len(values) for values in rings.values()),
        "rings_by_scenario": {key: len(values) for key, values in sorted(rings.items())},
        "subtype_distribution": dict(sorted(subtype.items())),
        "persona_distribution": dict(sorted(persona.items())),
    }


def _assert_frozen_bundle(output: Path) -> tuple[Any, Any, Any, dict[str, Any]]:
    freeze = _json(output / "freeze.json")
    policy = load_policy_config(version=POLICY_V2_VERSION)
    constraints = load_operating_constraints()
    cost = load_cost_profile(ROOT / "configs/costs/balanced-v1.yaml")
    model_metadata = _json(MODEL_DIRECTORY / "metadata.json")
    expected = {
        "checkpoint": "RISK-POLICY-V2 FROZEN",
        "external_seed_evaluated_at_checkpoint": False,
        "external_evaluation_seed": EXTERNAL_SEED,
        "policy_config_hash": policy.stable_hash(),
        "operating_constraints_hash": constraints.stable_hash(),
        "cost_config_hash": cost.stable_hash(),
        "model_metadata_hash": model_metadata["model_config_hash"],
    }
    for key, value in expected.items():
        if freeze.get(key) != value:
            raise RuntimeError(f"frozen policy-v2 bundle mismatch: {key}")
    return policy, constraints, cost, freeze


async def evaluate_external(output: Path) -> dict[str, Any]:
    policy_v2, _, cost, freeze = _assert_frozen_bundle(output)
    training = load_training_config(ROOT / "configs/ml/model-v2.yaml").model_copy(
        update={
            "benchmark_seed": EXTERNAL_SEED,
            "transaction_count": EXTERNAL_TRANSACTION_COUNT,
            "abuse_prevalence": EXTERNAL_ABUSE_PREVALENCE,
        }
    )
    dataset = await assemble_benchmark(training)
    model = RiskModel.load(MODEL_DIRECTORY)
    scores = model.predict_matrix(dataset.X, dataset.feature_names)
    examples: tuple[BacktestExample, ...] = _examples(dataset, scores)
    model_metadata = _json(MODEL_DIRECTORY / "metadata.json")
    policy_v1 = load_policy_config(version=POLICY_V1_VERSION)
    f1_threshold = float(model_metadata["selected_threshold"])
    f1_policy = policy_v1.model_copy(
        update={"verify_threshold": f1_threshold, "hold_threshold": f1_threshold}
    )
    comparison = {
        "phase5_validation_f1_threshold": evaluate_policy(examples, f1_policy, cost),
        "risk-policy-v1": evaluate_policy(examples, policy_v1, cost),
        "risk-policy-v2": evaluate_policy(examples, policy_v2, cost),
    }
    labels = np.asarray([item.label for item in dataset.metadata], dtype=np.int8)
    external = {
        "evaluation_type": "external held-out synthetic benchmark",
        "assumptions_label": "ILLUSTRATIVE SYNTHETIC POLICY ASSUMPTIONS",
        "dataset": _dataset_summary(dataset),
        "model_diagnostic": _model_diagnostic(labels, scores, f1_threshold),
        "pipeline_runtimes": dataset.runtimes,
        "policy_freeze_timestamp": freeze["frozen_at"],
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "external_metrics.json", external)
    write_json(output / "policy_comparison.json", comparison)
    write_json(output / "persona_external.json", comparison["risk-policy-v2"]["persona_actions"])
    write_json(output / "scenario_external.json", comparison["risk-policy-v2"]["scenario_actions"])
    metadata = _json(output / "metadata.json")
    metadata["external_evaluation"] = {
        "seed": EXTERNAL_SEED,
        "dataset_version": external["dataset"]["dataset_version"],
        "evaluated_at": external["evaluated_at"],
    }
    write_json(output / "metadata.json", metadata)
    return {"external": external, "comparison": comparison}


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze and externally evaluate risk-policy-v2")
    parser.add_argument("--output", type=Path, default=POLICY_V2_DIRECTORY)
    parser.add_argument("--evaluate-external", action="store_true")
    args = parser.parse_args()
    operation = (
        evaluate_external(args.output) if args.evaluate_external else freeze_policy(args.output)
    )
    print(json.dumps(asyncio.run(operation), indent=2, default=str))


if __name__ == "__main__":
    main()
