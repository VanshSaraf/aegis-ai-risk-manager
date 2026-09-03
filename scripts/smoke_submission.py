"""Exercise a running submission stack without rebuilding offline artifacts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

FORBIDDEN_OPERATIONAL_KEYS = {
    "dataset_split",
    "fraud_probability",
    "ground_truth",
    "ground_truth_label",
    "ground_truth_ring_id",
    "ground_truth_scenario",
    "persona",
    "scenario",
    "split",
    "truth_label",
}


def request_json(
    base_url: str, method: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - configured local stack URL
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} returned {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} could not reach {base_url}: {exc.reason}") from exc


def assert_truth_free(value: Any, location: str) -> None:
    if isinstance(value, dict):
        leaked = FORBIDDEN_OPERATIONAL_KEYS.intersection(key.lower() for key in value)
        if leaked:
            raise AssertionError(f"forbidden operational keys at {location}: {sorted(leaked)}")
        for key, child in value.items():
            assert_truth_free(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_truth_free(child, f"{location}[{index}]")


def operational_event() -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    event_time = datetime.now(UTC).replace(microsecond=0)
    return {
        "event_id": f"evt_submission_smoke_{suffix}",
        "event_time": event_time.isoformat(),
        "customer_ref": f"smoke_customer_{suffix}",
        "account_created_at": (event_time - timedelta(days=120)).isoformat(),
        "customer_segment": "RETAIL",
        "home_region": "IN-KA",
        "instrument_fingerprint": f"smoke_instrument_{suffix}",
        "instrument_type": "CARD",
        "issuer_region": "IN-MH",
        "device_fingerprint": f"smoke_device_{suffix}",
        "device_type": "MOBILE",
        "os_family": "ANDROID",
        "browser_family": "CHROME",
        "ip_hash": f"smoke_ip_{suffix}",
        "network_type": "MOBILE",
        "ip_region": "IN-KA",
        "address_fingerprint": f"smoke_address_{suffix}",
        "address_region": "IN-KA",
        "postal_prefix": "560",
        "merchant_ref": f"smoke_merchant_{suffix}",
        "merchant_category": "ECOMMERCE",
        "merchant_region": "IN-KA",
        "merchant_risk_baseline": 0.05,
        "amount_paise": 149_900,
        "payment_method": "CARD",
        "status": "AUTHORIZED",
    }


def run(base_url: str) -> dict[str, Any]:
    health = request_json(base_url, "GET", "/health")
    readiness = request_json(base_url, "GET", "/ready")
    if health.get("status") != "ok" or readiness.get("status") != "ready":
        raise AssertionError("stack is not healthy and ready")

    evaluation = request_json(base_url, "GET", "/api/v1/evaluation/summary")
    if evaluation.get("benchmark", {}).get("model_version") != "risk-lgbm-v2":
        raise AssertionError("frozen evaluation summary is unavailable")

    request_json(base_url, "GET", "/api/v1/dashboard/summary")
    transaction = request_json(base_url, "POST", "/api/v1/transactions", operational_event())
    transaction_id = str(transaction["transaction_public_id"])
    assessment = request_json(base_url, "POST", f"/api/v1/transactions/{transaction_id}/assess")
    investigation = request_json(
        base_url, "GET", f"/api/v1/transactions/{transaction_id}/investigation"
    )
    graph = request_json(base_url, "GET", f"/api/v1/transactions/{transaction_id}/graph")
    ordinary_operation = {
        "transaction": transaction,
        "assessment": assessment,
        "investigation": investigation,
        "graph": graph,
    }
    assert_truth_free(ordinary_operation, "ordinary_operation")

    demo = request_json(
        base_url, "POST", "/api/v1/demo/sessions", {"scenario": "IDENTITY_ROTATION"}
    )
    if demo.get("baseline_transactions") != 12 or demo.get("total_steps") != 18:
        raise AssertionError("canonical simulation counts do not match the frozen fixture")
    first_step = request_json(
        base_url,
        "POST",
        f"/api/v1/demo/sessions/{demo['session_id']}/step",
        {"expected_step": 0},
    )
    replay = request_json(
        base_url,
        "POST",
        f"/api/v1/demo/sessions/{demo['session_id']}/step",
        {"expected_step": 0},
    )
    if replay != first_step:
        raise AssertionError("replayed simulation step was not idempotent")

    final_step = first_step
    for expected_step in range(1, int(demo["total_steps"])):
        final_step = request_json(
            base_url,
            "POST",
            f"/api/v1/demo/sessions/{demo['session_id']}/step",
            {"expected_step": expected_step},
        )
    if not final_step.get("complete") or not final_step.get("assessment"):
        raise AssertionError("canonical simulation did not complete with an assessment")
    assert_truth_free(final_step, "simulation_step")

    final_transaction_id = str(final_step["transaction"]["public_id"])
    final_investigation = request_json(
        base_url, "GET", f"/api/v1/transactions/{final_transaction_id}/investigation"
    )
    final_graph = request_json(
        base_url, "GET", f"/api/v1/transactions/{final_transaction_id}/graph"
    )
    entity_node = next(
        (node for node in final_graph["nodes"] if node.get("type") not in {None, "TRANSACTION"}),
        None,
    )
    if entity_node is None:
        raise AssertionError("simulation graph did not expose an operational entity")
    entity_intelligence = request_json(
        base_url,
        "GET",
        f"/api/v1/entities/{entity_node['type']}/{entity_node['id']}",
    )
    entity_network = entity_intelligence.get("network")
    if (
        entity_intelligence.get("view_semantics") != "CURRENT_OBSERVED_HISTORY"
        or not isinstance(entity_network, dict)
        or entity_network.get("max_nodes") != 40
        or entity_network.get("max_edges") != 60
        or len(entity_network.get("nodes", [])) > entity_network["max_nodes"]
        or len(entity_network.get("edges", [])) > entity_network["max_edges"]
    ):
        raise AssertionError("entity intelligence response is not safe and bounded")
    dashboard = request_json(base_url, "GET", "/api/v1/dashboard/transactions?limit=50")
    assert_truth_free(
        {
            "final_step": final_step,
            "investigation": final_investigation,
            "graph": final_graph,
            "entity_intelligence": entity_intelligence,
            "dashboard": dashboard,
        },
        "simulation_operation",
    )
    if not any(
        item.get("transaction_id") == final_transaction_id for item in dashboard.get("items", [])
    ):
        raise AssertionError("final simulation transaction is missing from the dashboard")

    return {
        "status": "passed",
        "ordinary_transaction_id": transaction_id,
        "simulation": {
            "baseline_transactions": demo["baseline_transactions"],
            "animated_transactions": demo["total_steps"],
            "final_transaction_id": final_transaction_id,
            "final_action": final_step["assessment"]["action"],
            "final_model_score": final_step["assessment"]["model_score"],
            "graph_signal_count": final_step["assessment"]["graph_signal_count"],
        },
        "truth_exclusion": "passed",
        "entity_intelligence": "passed",
        "evaluation_model": evaluation["benchmark"]["model_version"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("AEGIS_API_BASE_URL", "http://localhost:8000"),
    )
    args = parser.parse_args()
    try:
        result = run(args.base_url.rstrip("/"))
    except (AssertionError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        print(f"submission smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
