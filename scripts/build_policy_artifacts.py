import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ml.training.artifacts import write_json
from ml.training.config import load_training_config
from ml.training.dataset import assemble_benchmark
from ml.training.splitting import manifest_hash, split_chronologically
from packages.graph_engine.engine import structural_score
from packages.graph_engine.registry import GRAPH_METRIC_NAMES
from packages.policy_engine.backtest import BacktestExample, evaluate_policy
from packages.policy_engine.config import load_policy_config
from packages.policy_engine.costs import load_cost_profile
from packages.policy_engine.domain import GraphEvidence, PolicyInput
from packages.policy_engine.engine import PolicyEngine
from packages.policy_engine.optimizer import optimize_thresholds
from packages.risk_engine.model import RiskModel

ROOT = Path(__file__).parents[1]
MODEL_DIRECTORY = ROOT / "ml/artifacts/model-v2"
POLICY_DIRECTORY = ROOT / "ml/artifacts/policy-v1"
COST_FILES = (
    "balanced-v1.yaml",
    "customer-protective-v1.yaml",
    "loss-averse-v1.yaml",
)


def _graph_evidence(metrics: dict[str, float]) -> tuple[GraphEvidence, ...]:
    signals: list[GraphEvidence] = []

    def add(code: str, observed: float, threshold: float) -> None:
        signals.append(
            GraphEvidence(
                code=code,
                strength=min(1.0, observed / max(threshold * 2, 1)),
                observed_value=observed,
                threshold=threshold,
                evidence={},
            )
        )

    if metrics["device_customer_degree"] >= 3:
        add("DEVICE_MULTI_CUSTOMER_CONCENTRATION", metrics["device_customer_degree"], 3)
    if metrics["device_instrument_degree"] >= 4:
        add("DEVICE_MULTI_INSTRUMENT_CONCENTRATION", metrics["device_instrument_degree"], 4)
    expansion = max(metrics["component_new_edges_10m"], metrics["device_new_identities_10m"])
    if metrics["component_new_edges_10m"] >= 6 or metrics["device_new_identities_10m"] >= 4:
        add("RAPID_RELATIONSHIP_EXPANSION", expansion, 6)
    if metrics["components_bridged_by_transaction"] >= 1:
        add("MULTI_COMPONENT_BRIDGE", metrics["components_bridged_by_transaction"], 1)
    if (
        metrics["component_customer_count"] >= 3
        and metrics["component_instrument_count"] >= 3
        and metrics["component_multipartite_density"] >= 0.15
    ):
        add("DENSE_MULTI_ENTITY_STRUCTURE", metrics["component_multipartite_density"], 0.15)
    return tuple(signals)


def _examples(dataset, scores: np.ndarray) -> tuple[BacktestExample, ...]:
    amounts = {
        event.facts.event_id: event.facts.amount_paise for event in dataset.synthetic_dataset.events
    }
    graph_start = len(dataset.feature_names) - len(GRAPH_METRIC_NAMES)
    examples: list[BacktestExample] = []
    for index, metadata in enumerate(dataset.metadata):
        metrics = {
            name: float(dataset.X[index, graph_start + offset])
            for offset, name in enumerate(GRAPH_METRIC_NAMES)
        }
        score = structural_score(
            device_customer_degree=int(metrics["device_customer_degree"]),
            device_instrument_degree=int(metrics["device_instrument_degree"]),
            customer_count=int(metrics["component_customer_count"]),
            instrument_count=int(metrics["component_instrument_count"]),
            device_count=int(metrics["component_device_count"]),
            density=metrics["component_multipartite_density"],
            recent_edges=int(metrics["component_new_edges_10m"]),
        )
        cluster_id = (
            f"offline-structural:{metadata.transaction_id}"
            if bool(dataset.graph_baseline[index])
            else None
        )
        examples.append(
            BacktestExample(
                policy_input=PolicyInput(
                    transaction_public_id=metadata.transaction_id,
                    model_version="risk-lgbm-v2",
                    model_score=float(scores[index]),
                    feature_version="features-v1",
                    graph_version="graph-v1",
                    graph_structure_score=score,
                    graph_signals=_graph_evidence(metrics),
                    detected_cluster_id=cluster_id,
                    computed_at=metadata.event_time,
                ),
                amount_paise=amounts[metadata.transaction_id],
                label=metadata.label,
                persona=metadata.persona,
                scenario=metadata.scenario,
            )
        )
    return tuple(examples)


def _select(
    examples: tuple[BacktestExample, ...], indices: np.ndarray
) -> tuple[BacktestExample, ...]:
    return tuple(examples[int(index)] for index in indices)


def _decision_examples(examples: tuple[BacktestExample, ...], policy) -> dict[str, dict[str, Any]]:
    engine = PolicyEngine(policy)
    selected: dict[str, dict[str, Any]] = {}
    for example in examples:
        assessment, decision = engine.assess(example.policy_input)
        if decision.action.value in selected:
            continue
        selected[decision.action.value] = {
            "transaction_public_id": assessment.transaction_public_id,
            "model_version": assessment.model_version,
            "model_score": assessment.model_score,
            "score_semantics": "uncalibrated model score; not a fraud probability",
            "graph_version": assessment.graph_version,
            "graph_structure_score": assessment.graph_structure_score,
            "graph_signals": [signal.code for signal in assessment.graph_signals],
            "detected_cluster_id": assessment.detected_cluster_id,
            "severity": assessment.severity.value,
            "action": decision.action.value,
            "requires_human_review": decision.requires_human_review,
            "reason_codes": list(decision.reason_codes),
        }
        if len(selected) == 5:
            break
    return selected


async def build(output: Path) -> dict[str, Any]:
    training = load_training_config(ROOT / "configs/ml/model-v2.yaml")
    dataset = await assemble_benchmark(training)
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
    expected_split = json.loads((MODEL_DIRECTORY / "split_manifest.json").read_text())
    if manifest_hash(split.manifest) != manifest_hash(expected_split):
        raise RuntimeError("reconstructed policy dataset does not match frozen model-v2 split")
    model = RiskModel.load(MODEL_DIRECTORY)
    scores = model.predict_matrix(dataset.X, dataset.feature_names)
    examples = _examples(dataset, scores)
    validation = _select(examples, split.validation)
    test = _select(examples, split.test)
    base_policy = load_policy_config(version="risk-policy-v1")

    sensitivity: dict[str, Any] = {}
    optimization_results = {}
    for filename in COST_FILES:
        profile = load_cost_profile(ROOT / "configs/costs" / filename)
        result = optimize_thresholds(validation, base_policy, profile)
        optimization_results[profile.cost_profile_version] = (profile, result)
        sensitivity[profile.cost_profile_version] = {
            "policy": result.policy.model_dump(mode="json"),
            "validation": result.validation_metrics,
            "test": evaluate_policy(test, result.policy, profile),
            "objective": result.objective,
            "tie_break": result.tie_break,
        }

    balanced_profile, balanced = optimization_results["balanced-v1"]
    policy = balanced.policy
    if balanced.validation_metrics["action_counts"]["VERIFY"] == 0:
        raise RuntimeError("policy freeze requires a non-empty validation VERIFY band")
    model_metadata = json.loads((MODEL_DIRECTORY / "metadata.json").read_text())
    freeze = {
        "checkpoint": "RISK-POLICY-V1 FROZEN",
        "policy_version": policy.policy_version,
        "model_version": policy.model_version,
        "feature_version": policy.feature_version,
        "graph_version": policy.graph_version,
        "cost_profile": balanced_profile.cost_profile_version,
        "verify_threshold": policy.verify_threshold,
        "hold_threshold": policy.hold_threshold,
        "graph_corroboration": policy.graph_corroboration.model_dump(mode="json"),
        "policy_config_hash": policy.stable_hash(),
        "cost_config_hash": balanced_profile.stable_hash(),
        "model_metadata_hash": model_metadata["model_config_hash"],
        "feature_schema_hash": model_metadata["feature_schema_hash"],
        "graph_schema_hash": model_metadata["graph_schema_hash"],
        "threshold_selection_data": "validation only",
        "objective": balanced.objective,
        "tie_break": balanced.tie_break,
        "test_evaluated_at_checkpoint": False,
        "frozen_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "freeze.json", freeze)

    # Test is evaluated only after the freeze artifact exists.
    test_metrics = evaluate_policy(test, policy, balanced_profile)
    f1_policy = base_policy.model_copy(
        update={
            "verify_threshold": float(model_metadata["selected_threshold"]),
            "hold_threshold": float(model_metadata["selected_threshold"]),
        }
    )
    f1_comparison = {
        "description": "different objectives: classifier validation-F1 versus synthetic cost",
        "validation_f1_threshold_policy": {
            "threshold": model_metadata["selected_threshold"],
            "test": evaluate_policy(test, f1_policy, balanced_profile),
        },
        "cost_aware_policy": {"test": test_metrics},
    }
    write_json(output / "policy.json", policy.model_dump(mode="json"))
    write_json(output / "cost_profile.json", balanced_profile.model_dump(mode="json"))
    write_json(output / "validation_frontier.json", list(balanced.frontier))
    write_json(output / "validation_metrics.json", balanced.validation_metrics)
    write_json(output / "test_metrics.json", test_metrics)
    write_json(output / "sensitivity.json", sensitivity)
    write_json(output / "f1_threshold_comparison.json", f1_comparison)
    write_json(output / "decision_examples.json", _decision_examples(test, policy))
    metadata = {
        "policy_version": policy.policy_version,
        "cost_profile_version": balanced_profile.cost_profile_version,
        "dataset_version": dataset.manifest.dataset_version,
        "split_manifest_hash": manifest_hash(split.manifest),
        "policy_config_hash": policy.stable_hash(),
        "cost_config_hash": balanced_profile.stable_hash(),
        "model_version": model_metadata["model_version"],
        "model_metadata_hash": model_metadata["model_config_hash"],
        "feature_schema_hash": model_metadata["feature_schema_hash"],
        "graph_schema_hash": model_metadata["graph_schema_hash"],
        "candidate_threshold_count": balanced.candidate_threshold_count,
        "evaluated_pair_count": balanced.evaluated_pair_count,
        "test_evaluated_at": datetime.now(UTC).isoformat(),
        "pipeline_runtimes": dataset.runtimes,
    }
    write_json(output / "metadata.json", metadata)
    return {
        "freeze": freeze,
        "validation": balanced.validation_metrics,
        "test": test_metrics,
        "sensitivity": sensitivity,
        "examples": _decision_examples(test, policy),
        "metadata": metadata,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize and freeze risk-policy-v1 on validation")
    parser.add_argument("--output", type=Path, default=POLICY_DIRECTORY)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(build(args.output)), indent=2, default=str))


if __name__ == "__main__":
    main()
