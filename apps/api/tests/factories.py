from datetime import UTC, datetime, timedelta
from typing import Any


def raw_event_payload(event_id: str = "evt_001", **overrides: Any) -> dict[str, Any]:
    event_time = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)
    payload: dict[str, Any] = {
        "event_id": event_id,
        "event_type": "payment.transaction",
        "event_version": "1.0",
        "event_time": event_time.isoformat(),
        "customer_ref": "synthetic_customer_001",
        "account_created_at": (event_time - timedelta(days=30)).isoformat(),
        "customer_segment": "RETAIL",
        "home_region": "IN-KA",
        "instrument_fingerprint": "inst_fp_001",
        "instrument_type": "CARD",
        "issuer_region": "IN-MH",
        "device_fingerprint": "device_fp_001",
        "device_type": "MOBILE",
        "os_family": "ANDROID",
        "browser_family": "CHROME",
        "ip_hash": "ip_hash_001",
        "network_type": "MOBILE",
        "ip_region": "IN-KA",
        "address_fingerprint": "address_fp_001",
        "address_region": "IN-KA",
        "postal_prefix": "560",
        "merchant_ref": "synthetic_merchant_001",
        "merchant_category": "ECOMMERCE",
        "merchant_region": "IN-KA",
        "merchant_risk_baseline": 0.05,
        "amount_paise": 189999,
        "currency": "INR",
        "payment_method": "CARD",
        "status": "AUTHORIZED",
    }
    payload.update(overrides)
    return payload
