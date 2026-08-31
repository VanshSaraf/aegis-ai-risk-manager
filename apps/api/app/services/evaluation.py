import json
from pathlib import Path
from typing import Any

from apps.api.app.schemas.api import (
    EvaluationBenchmark,
    EvaluationClassificationMetrics,
    EvaluationModelResult,
    EvaluationPolicyExternal,
    EvaluationSummary,
)

ARTIFACT_ROOT = Path(__file__).resolve().parents[4] / "ml" / "artifacts"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _classification_metrics(value: dict[str, Any]) -> EvaluationClassificationMetrics:
    return EvaluationClassificationMetrics(
        pr_auc=float(value["pr_auc"]),
        precision=float(value["precision"]),
        recall=float(value["recall"]),
        f1=float(value["f1"]),
        false_positive=int(value["false_positive"]),
        false_negative=int(value["false_negative"]),
        threshold=float(value["threshold"]),
    )


def load_evaluation_summary(artifact_root: Path = ARTIFACT_ROOT) -> EvaluationSummary:
    model_directory = artifact_root / "model-v2"
    policy_directory = artifact_root / "policy-v2"
    test_metrics = _read(model_directory / "test_metrics.json")
    benchmark = _read(model_directory / "benchmark.json")["dataset"]
    metadata = _read(model_directory / "metadata.json")
    external = _read(policy_directory / "external_metrics.json")
    policy_comparison = _read(policy_directory / "policy_comparison.json")["risk-policy-v2"]
    constraints = _read(policy_directory / "operating_constraints.json")

    model_specs = (
        ("TABULAR", "Tabular", "tabular_lightgbm"),
        ("GRAPH", "Graph", "graph_lightgbm"),
        ("COMBINED", "Combined", "combined_lightgbm"),
    )
    models = [
        EvaluationModelResult(
            code=code,
            display_name=display_name,
            metrics=_classification_metrics(test_metrics[artifact_key]["selected_threshold"]),
        )
        for code, display_name, artifact_key in model_specs
    ]
    operating = policy_comparison["operating_metrics"]
    policy_external = EvaluationPolicyExternal(
        policy_version="risk-policy-v2",
        abuse_intervention_recall=float(operating["abuse_intervention_recall"]),
        legitimate_intervention_rate=float(operating["legitimate_intervention_rate"]),
        legitimate_severe_intervention_rate=float(operating["legitimate_severe_intervention_rate"]),
        total_human_review_rate=float(operating["total_human_review_rate"]),
        allowed_abuse_transactions=int(policy_comparison["intervention"]["false_negative"]),
        constraints_generalized=all(
            (
                operating["abuse_intervention_recall"]
                >= constraints["minimum_abuse_intervention_recall"],
                operating["legitimate_intervention_rate"]
                <= constraints["maximum_legitimate_intervention_rate"],
                operating["legitimate_severe_intervention_rate"]
                <= constraints["maximum_legitimate_severe_intervention_rate"],
                operating["total_human_review_rate"]
                <= constraints["maximum_total_human_review_rate"],
                operating["maximum_legitimate_persona_severe_intervention_rate"]
                <= constraints["maximum_any_legitimate_persona_severe_intervention_rate"],
            )
        ),
        validation_legitimate_intervention_budget=float(
            constraints["maximum_legitimate_intervention_rate"]
        ),
        estimated_net_protected_value_paise=int(
            policy_comparison["costs_paise"]["estimated_net_protected_value"]
        ),
        cost_assumptions_label=str(policy_comparison["assumptions_label"]),
    )
    return EvaluationSummary(
        benchmark=EvaluationBenchmark(
            evaluation_type="frozen held-out synthetic test partition",
            dataset_version=str(benchmark["dataset_version"]),
            generator_version=str(benchmark["generator_version"]),
            seed=int(benchmark["seed"]),
            transaction_count=int(benchmark["transaction_count"]),
            legitimate_count=int(benchmark["legitimate_count"]),
            coordinated_abuse_count=int(benchmark["coordinated_abuse_count"]),
            model_version=str(metadata["model_version"]),
        ),
        models=models,
        external_model=EvaluationModelResult(
            code="EXTERNAL_COMBINED",
            display_name="Combined · external seed 91573",
            metrics=_classification_metrics(external["model_diagnostic"]),
        ),
        external_seed=int(external["dataset"]["seed"]),
        external_dataset_version=str(external["dataset"]["dataset_version"]),
        policy_external=policy_external,
        methodology=[
            "Point-in-time features with a strict historical cutoff",
            "Ring/group isolation across data partitions",
            "Validation-only threshold selection",
            "Frozen test evaluation after model selection",
            "Fresh external seed evaluated after policy freeze",
            "No retuning after external results",
        ],
        limitations=[
            "Synthetic data only; these are not production or Razorpay performance claims",
            "Model output is an uncalibrated risk ranking score, not a fraud probability",
            "The structural cluster detector can over-fragment coordinated groups",
            "External policy friction exceeded some validation operating budgets",
            "Economic assumptions are illustrative and not a production savings model",
            "Aegis makes bounded recommendations and never autonomously applies a permanent block",
        ],
        artifact_sources=[
            "ml/artifacts/model-v2/test_metrics.json",
            "ml/artifacts/model-v2/benchmark.json",
            "ml/artifacts/model-v2/metadata.json",
            "ml/artifacts/policy-v2/external_metrics.json",
            "ml/artifacts/policy-v2/policy_comparison.json",
            "ml/artifacts/policy-v2/operating_constraints.json",
        ],
    )
