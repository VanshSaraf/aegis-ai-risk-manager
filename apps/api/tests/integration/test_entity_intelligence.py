from datetime import UTC, datetime, timedelta

from apps.api.tests.factories import raw_event_payload


async def test_entity_intelligence_supports_all_operational_entity_types(client) -> None:
    created = await client.post(
        "/api/v1/transactions",
        json=raw_event_payload("evt_entity_types"),
    )
    assert created.status_code == 201
    transaction = created.json()
    entities = {
        "CUSTOMER": transaction["customer_public_id"],
        "DEVICE": transaction["device_public_id"],
        "PAYMENT_INSTRUMENT": transaction["payment_instrument_public_id"],
        "IP_ADDRESS": transaction["ip_address_public_id"],
        "ADDRESS": transaction["address_public_id"],
    }

    for entity_type, public_id in entities.items():
        response = await client.get(f"/api/v1/entities/{entity_type}/{public_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["view_semantics"] == "CURRENT_OBSERVED_HISTORY"
        assert body["entity"]["entity_type"] == entity_type
        assert body["entity"]["public_id"] == public_id
        assert body["entity"]["transaction_count"] == 1
        assert body["network"]["nodes"][0]["is_center"] is True


async def test_entity_intelligence_is_bounded_grounded_and_truth_free(client) -> None:
    start = datetime(2026, 8, 30, 10, tzinfo=UTC)
    device_id = None
    final_transaction_id = None
    for index in range(45):
        created = await client.post(
            "/api/v1/transactions",
            json=raw_event_payload(
                f"evt_entity_bounded_{index}",
                event_time=(start + timedelta(minutes=index)).isoformat(),
                customer_ref=f"entity-bounded-customer-{index}",
                instrument_fingerprint=f"entity-bounded-instrument-{index}",
                device_fingerprint="entity-shared-device",
            ),
        )
        assert created.status_code == 201
        device_id = created.json()["device_public_id"]
        final_transaction_id = created.json()["transaction_public_id"]

    assert device_id is not None
    assert final_transaction_id is not None
    assert (
        await client.post(f"/api/v1/transactions/{final_transaction_id}/assess")
    ).status_code == 200

    response = await client.get(f"/api/v1/entities/DEVICE/{device_id}")
    assert response.status_code == 200
    body = response.json()
    network = body["network"]
    assert len(network["nodes"]) <= network["max_nodes"] == 40
    assert len(network["edges"]) <= network["max_edges"] == 60
    assert network["truncated"] is True
    assert body["summary"]["visible_relationships"] == len(network["edges"])
    assert body["summary"]["visible_devices"] == 1
    assert sum(
        body["summary"][field]
        for field in (
            "visible_customers",
            "visible_devices",
            "visible_instruments",
            "visible_ips",
            "visible_addresses",
        )
    ) == len(network["nodes"])
    assert body["entity"]["transaction_count"] == 45
    assert len(body["recent_transactions"]) == 12
    assert body["recent_transactions"][0]["transaction_id"] == final_transaction_id
    assert body["risk_context"]["highest_recent_transaction_score"] is not None
    assert body["risk_context"]["recent_action_counts"]["verify"] == 1
    assert body["structural_context"]
    safe_prefixes = {
        "CUSTOMER": "cus_",
        "DEVICE": "dev_",
        "PAYMENT_INSTRUMENT": "card_",
        "IP_ADDRESS": "ip_",
        "ADDRESS": "addr_",
    }
    assert all(node["id"].startswith(safe_prefixes[node["type"]]) for node in network["nodes"])
    assert all(
        transaction["transaction_id"].startswith("txn_")
        for transaction in body["recent_transactions"]
    )

    serialized = str(body).lower()
    for forbidden in (
        "ground_truth",
        "truth_label",
        "ring_id",
        "scenario",
        "persona",
        "dataset_split",
        "fraud_probability",
        "entity-shared-device",
        "entity-bounded-customer",
        "entity-bounded-instrument",
        "fingerprint",
        "source_ref",
    ):
        assert forbidden not in serialized


async def test_entity_intelligence_validates_type_and_missing_entity(client) -> None:
    invalid_type = await client.get("/api/v1/entities/MERCHANT/mer_missing")
    assert invalid_type.status_code == 422
    invalid_neighbors_type = await client.get("/api/v1/entities/MERCHANT/mer_missing/neighbors")
    assert invalid_neighbors_type.status_code == 422

    missing = await client.get("/api/v1/entities/DEVICE/dev_missing")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "entity not found"}
