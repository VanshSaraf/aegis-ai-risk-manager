import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pytest

from apps.api.app.core.enums import ScenarioType
from ml.evaluation.metrics import (
    binary_metrics,
    persona_false_positives,
    scenario_recall,
    select_validation_f1_threshold,
)
from ml.training.config import (
    LightGBMCandidate,
    SplitRatios,
    TrainingConfig,
    load_training_config,
)
from ml.training.dataset import COMBINED_FEATURE_NAMES, EvaluationMetadata, assemble_benchmark
from ml.training.leakage import audit_model_matrix
from ml.training.splitting import build_abuse_supergroups, split_chronologically
from ml.training.train import train_lightgbm_variant
from packages.graph_engine.registry import GRAPH_METRIC_NAMES
from packages.risk_engine.features.registry import FEATURE_NAMES
from packages.risk_engine.model import RiskModel


def _metadata() -> tuple[EvaluationMetadata, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    items: list[EvaluationMetadata] = []
    index = 0
    abuse_scenarios = [
        scenario for scenario in ScenarioType if scenario != ScenarioType.NORMAL_TRAFFIC
    ]
    for partition_day in (0, 10, 20):
        for offset in range(8):
            items.append(
                EvaluationMetadata(
                    f"legit-{index:03d}",
                    start + timedelta(days=partition_day, minutes=offset),
                    0,
                    ScenarioType.NORMAL_TRAFFIC.value,
                    None,
                    "STANDARD_RETAIL",
                    (),
                )
            )
            index += 1
        for offset, scenario in enumerate(abuse_scenarios, start=10):
            ring = f"ring-{partition_day}-{scenario.value}"
            items.append(
                EvaluationMetadata(
                    f"abuse-{index:03d}",
                    start + timedelta(days=partition_day, minutes=offset),
                    1,
                    scenario.value,
                    ring,
                    None,
                    (f"DEVICE:{ring}", f"IP:{ring}"),
                )
            )
            index += 1
    return tuple(sorted(items, key=lambda item: (item.event_time, item.transaction_id)))


def _training_config() -> TrainingConfig:
    return TrainingConfig(
        model_version="risk-lgbm-v1",
        benchmark_seed=73129,
        transaction_count=100,
        abuse_prevalence=0.2,
        feature_version="features-v1",
        graph_version="graph-v1",
        split_ratios=SplitRatios(train=0.7, validation=0.15, test=0.15),
        random_seed=73129,
        early_stopping_rounds=5,
        threshold_selection_objective="validation_f1",
        lightgbm_candidates=(
            LightGBMCandidate(
                name="smoke",
                num_leaves=7,
                min_child_samples=5,
                learning_rate=0.1,
                n_estimators=30,
                colsample_bytree=1.0,
                reg_lambda=1.0,
            ),
        ),
    )


def test_registered_model_input_is_exactly_52_plus_25_equals_77() -> None:
    assert len(FEATURE_NAMES) == 52
    assert len(GRAPH_METRIC_NAMES) == 25
    assert COMBINED_FEATURE_NAMES == FEATURE_NAMES + GRAPH_METRIC_NAMES
    assert len(COMBINED_FEATURE_NAMES) == 77
    assert COMBINED_FEATURE_NAMES == tuple(COMBINED_FEATURE_NAMES)


def test_model_schema_excludes_truth_ids_and_outcomes() -> None:
    forbidden = {
        "ground_truth_label",
        "ground_truth_scenario",
        "ground_truth_ring_id",
        "persona",
        "transaction_public_id",
        "status",
        "failure_code",
        "cluster_public_id",
    }
    assert forbidden.isdisjoint(COMBINED_FEATURE_NAMES)


def test_versioned_training_config_is_deterministic() -> None:
    path = Path("configs/ml/model-v1.yaml")
    first = load_training_config(path)
    second = load_training_config(path)
    assert first == second
    assert first.stable_hash() == second.stable_hash()
    assert (first.benchmark_seed, first.transaction_count) == (73129, 50_000)


@pytest.mark.asyncio
async def test_dataset_assembly_joins_registered_inputs_and_keeps_truth_separate() -> None:
    config = load_training_config(Path("configs/ml/model-v1.yaml")).model_copy(
        update={"transaction_count": 250}
    )
    dataset = await assemble_benchmark(config)
    assert dataset.X.shape == (250, 77)
    assert len({item.transaction_id for item in dataset.predictive_examples}) == 250
    assert tuple(item.transaction_id for item in dataset.predictive_examples) == tuple(
        item.transaction_id for item in dataset.metadata
    )
    assert not hasattr(dataset.predictive_examples[0], "label")
    assert hasattr(dataset.metadata[0], "label")


def test_temporal_grouped_split_is_deterministic_and_isolated() -> None:
    metadata = _metadata()
    ratios = SplitRatios(train=0.7, validation=0.15, test=0.15)
    first = split_chronologically(metadata, ratios)
    second = split_chronologically(metadata, ratios)
    assert np.array_equal(first.train, second.train)
    assert np.array_equal(first.validation, second.validation)
    assert np.array_equal(first.test, second.test)
    index_sets = [set(first.train), set(first.validation), set(first.test)]
    assert not index_sets[0] & index_sets[1]
    assert not index_sets[0] & index_sets[2]
    assert not index_sets[1] & index_sets[2]
    ring_sets = [
        {metadata[index].ring_id for index in indices if metadata[index].ring_id}
        for indices in (first.train, first.validation, first.test)
    ]
    assert not ring_sets[0] & ring_sets[1]
    assert not ring_sets[1] & ring_sets[2]
    assert max(metadata[index].event_time for index in first.train) < min(
        metadata[index].event_time for index in first.validation
    )
    assert max(metadata[index].event_time for index in first.validation) < min(
        metadata[index].event_time for index in first.test
    )
    for indices in (first.train, first.validation, first.test):
        assert {metadata[index].label for index in indices} == {0, 1}
        assert {metadata[index].scenario for index in indices if metadata[index].label} == {
            scenario.value for scenario in ScenarioType if scenario != ScenarioType.NORMAL_TRAFFIC
        }


def test_abuse_identity_overlap_forms_evaluation_only_supergroup() -> None:
    metadata = list(_metadata())
    left = next(index for index, item in enumerate(metadata) if item.ring_id)
    right = next(
        index
        for index, item in enumerate(metadata)
        if item.ring_id and item.ring_id != metadata[left].ring_id
    )
    shared = "DEVICE:shared-abuse-device"
    metadata[left] = replace(
        metadata[left], abuse_entities=metadata[left].abuse_entities + (shared,)
    )
    metadata[right] = replace(
        metadata[right], abuse_entities=metadata[right].abuse_entities + (shared,)
    )
    groups, overlaps = build_abuse_supergroups(tuple(metadata))
    assert groups[metadata[left].ring_id] == groups[metadata[right].ring_id]
    assert overlaps[shared] == tuple(sorted((metadata[left].ring_id, metadata[right].ring_id)))


def test_leakage_audit_rejects_forbidden_column_and_label_alias() -> None:
    y = np.asarray([0, 1, 0, 1])
    with pytest.raises(ValueError, match="forbidden predictive columns"):
        audit_model_matrix(
            np.zeros((4, 1)), y, ("ground_truth_label",), expected_names=("ground_truth_label",)
        )
    with pytest.raises(ValueError, match="exact label aliases"):
        audit_model_matrix(y.reshape(-1, 1), y, ("safe_feature",), expected_names=("safe_feature",))


def test_leakage_audit_reports_constant_and_univariate_auc() -> None:
    y = np.asarray([0, 0, 1, 1])
    X = np.asarray([[1, 0], [1, 0.2], [1, 0.8], [1, 1]])
    audit = audit_model_matrix(X, y, ("constant", "signal"), expected_names=("constant", "signal"))
    assert audit.constant_features == ("constant",)
    assert audit.strongest_feature == "signal"
    assert audit.strongest_univariate_auc == 1.0
    assert audit.suspicious_features == ("signal",)


def test_validation_threshold_and_metrics_known_fixture() -> None:
    y = np.asarray([0, 0, 1, 1])
    scores = np.asarray([0.1, 0.4, 0.6, 0.9])
    threshold = select_validation_f1_threshold(y, scores)
    metrics = binary_metrics(y, scores, threshold)
    assert threshold == pytest.approx(0.6)
    assert metrics["pr_auc"] == pytest.approx(1.0)
    assert metrics["precision"] == metrics["recall"] == metrics["f1"] == 1.0
    assert metrics["true_positive"] == metrics["true_negative"] == 2


def test_scenario_and_persona_diagnostics() -> None:
    metadata = _metadata()
    scores = np.asarray([item.label for item in metadata], dtype=float)
    scenarios = scenario_recall(metadata, scores, 0.5)
    personas = persona_false_positives(metadata, scores, 0.5)
    assert all(item["recall"] == 1.0 for item in scenarios.values())
    assert personas["STANDARD_RETAIL"]["false_positive"] == 0


def test_lightgbm_ablation_smoke_is_deterministic() -> None:
    rng = np.random.default_rng(73129)
    X = rng.normal(size=(160, 77))
    y = (X[:, 0] + X[:, 52] > 0.5).astype(np.int8)
    config = _training_config()
    variants = []
    for name, column_slice, names in (
        ("tabular", slice(0, 52), FEATURE_NAMES),
        ("graph", slice(52, None), GRAPH_METRIC_NAMES),
        ("combined", slice(None), COMBINED_FEATURE_NAMES),
    ):
        variants.append(
            train_lightgbm_variant(
                name,
                names,
                X[:120, column_slice],
                y[:120],
                X[120:, column_slice],
                y[120:],
                config,
            )
        )
    repeated = train_lightgbm_variant(
        "combined",
        COMBINED_FEATURE_NAMES,
        X[:120],
        y[:120],
        X[120:],
        y[120:],
        config,
    )
    assert {len(item.feature_names) for item in variants} == {25, 52, 77}
    assert np.allclose(variants[-1].validation_scores, repeated.validation_scores, atol=1e-12)


def test_native_model_reload_and_schema_guardrails(tmp_path: Path) -> None:
    rng = np.random.default_rng(12)
    X = rng.normal(size=(80, 77))
    y = (X[:, 0] > 0).astype(int)
    model = lgb.LGBMClassifier(n_estimators=10, verbosity=-1, random_state=1, n_jobs=1)
    model.fit(X, y, feature_name=list(COMBINED_FEATURE_NAMES))
    model.booster_.save_model(str(tmp_path / "model.txt"))
    metadata = {
        "model_version": "risk-lgbm-v1",
        "feature_version": "features-v1",
        "graph_version": "graph-v1",
        "feature_count": 77,
        "feature_order": list(COMBINED_FEATURE_NAMES),
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    loaded = RiskModel.load(tmp_path)
    assert np.allclose(model.booster_.predict(X), loaded.predict_matrix(X, COMBINED_FEATURE_NAMES))
    metadata["graph_version"] = "wrong"
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="graph schema version mismatch"):
        RiskModel.load(tmp_path)


@pytest.mark.parametrize("version", ("risk-lgbm-v1", "risk-lgbm-v2"))
def test_committed_model_artifact_loads_with_registered_schema(version: str) -> None:
    artifact = Path("ml/artifacts") / version.replace("risk-lgbm", "model")
    loaded = RiskModel.load(artifact)
    assert loaded.metadata["model_version"] == version
    assert loaded.feature_order == COMBINED_FEATURE_NAMES
