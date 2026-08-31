from httpx import ASGITransport, AsyncClient

from apps.api.app.services.evaluation import load_evaluation_summary


def test_evaluation_summary_loads_frozen_artifacts_with_provenance() -> None:
    summary = load_evaluation_summary()
    results = {item.code: item.metrics for item in summary.models}

    assert summary.benchmark.dataset_version == "synthetic-v2-seed-88421-b4d7eb9e6d"
    assert summary.benchmark.transaction_count == 50_000
    assert results["TABULAR"].pr_auc == 0.9748940217450285
    assert results["TABULAR"].false_positive == 83
    assert results["GRAPH"].pr_auc == 0.9965063326704237
    assert results["GRAPH"].false_positive == 13
    assert results["COMBINED"].pr_auc == 0.9983653151407939
    assert results["COMBINED"].false_positive == 4
    assert summary.external_seed == 91573
    assert summary.external_model.metrics.pr_auc == 0.9858323924950751
    assert summary.policy_external.constraints_generalized is False
    assert all(source.startswith("ml/artifacts/") for source in summary.artifact_sources)


async def test_evaluation_endpoint_is_db_independent_and_separate_from_operations() -> None:
    from apps.api.app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/evaluation/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["benchmark"]["evaluation_type"] == "frozen held-out synthetic test partition"
    assert body["benchmark"]["model_version"] == "risk-lgbm-v2"
    assert "transaction_id" not in body
    assert "investigation" not in body
