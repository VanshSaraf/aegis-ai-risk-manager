"""Small truth-free showcase fixtures; separate from the synthetic-v2 benchmark."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from apps.api.app.core.enums import NetworkType, TransactionStatus
from apps.api.app.schemas.contracts import RawPaymentEvent

BASELINE_TRANSACTION_COUNT = 12
IDENTITY_ROTATION_STEP_COUNT = 18


@dataclass(frozen=True, slots=True)
class DemoSequence:
    baseline: tuple[RawPaymentEvent, ...]
    showcase: tuple[RawPaymentEvent, ...]


def _event(
    *,
    namespace: str,
    kind: str,
    index: int,
    event_time: datetime,
    customer_ref: str,
    instrument_fingerprint: str,
    device_fingerprint: str,
    ip_hash: str,
    address_fingerprint: str,
    amount_paise: int,
    status: TransactionStatus,
) -> RawPaymentEvent:
    return RawPaymentEvent(
        event_id=f"evt_demo_{namespace}_{kind}_{index:02d}",
        event_time=event_time,
        customer_ref=customer_ref,
        account_created_at=event_time - timedelta(days=120 if kind == "baseline" else 2),
        customer_segment="RETAIL",
        home_region="IN-KA",
        instrument_fingerprint=instrument_fingerprint,
        instrument_type="CARD",
        issuer_region="IN-MH",
        device_fingerprint=device_fingerprint,
        device_type="MOBILE",
        os_family="ANDROID",
        browser_family="CHROME",
        ip_hash=ip_hash,
        network_type=NetworkType.MOBILE if kind == "baseline" else NetworkType.DATACENTER,
        ip_region="IN-KA",
        address_fingerprint=address_fingerprint,
        address_region="IN-KA",
        postal_prefix="560",
        merchant_ref=f"demo_{namespace}_merchant",
        merchant_category="ECOMMERCE",
        merchant_region="IN-KA",
        merchant_risk_baseline=0.05,
        amount_paise=amount_paise,
        payment_method="CARD",
        status=status,
        failure_code="PAYMENT_AUTHENTICATION_FAILED"
        if status == TransactionStatus.FAILED
        else None,
    )


def build_identity_rotation_demo(namespace: str, base_time: datetime) -> DemoSequence:
    """Build a plausible deterministic showcase without benchmark ground truth."""
    baseline = tuple(
        _event(
            namespace=namespace,
            kind="baseline",
            index=index,
            event_time=base_time - timedelta(minutes=BASELINE_TRANSACTION_COUNT - index),
            customer_ref=f"demo_{namespace}_baseline_customer_{index % 3:02d}",
            instrument_fingerprint=f"demo_{namespace}_baseline_instrument_{index % 3:02d}",
            device_fingerprint=f"demo_{namespace}_baseline_device_{index % 3:02d}",
            ip_hash=f"demo_{namespace}_baseline_ip_{index % 3:02d}",
            address_fingerprint=f"demo_{namespace}_baseline_address_{index % 3:02d}",
            amount_paise=85_000 + index * 7_500,
            status=TransactionStatus.AUTHORIZED,
        )
        for index in range(BASELINE_TRANSACTION_COUNT)
    )
    showcase = tuple(
        _event(
            namespace=namespace,
            kind="rotation",
            index=index,
            event_time=base_time + timedelta(seconds=30 * (index + 1)),
            customer_ref=f"demo_{namespace}_rotating_customer_{index:02d}",
            instrument_fingerprint=f"demo_{namespace}_rotating_instrument_{index % 6:02d}",
            device_fingerprint=f"demo_{namespace}_shared_device",
            ip_hash=f"demo_{namespace}_shared_ip",
            address_fingerprint=f"demo_{namespace}_rotating_address_{index % 3:02d}",
            amount_paise=119_900 + index * 13_700,
            status=(TransactionStatus.FAILED if index < 8 else TransactionStatus.AUTHORIZED),
        )
        for index in range(IDENTITY_ROTATION_STEP_COUNT)
    )
    return DemoSequence(baseline=baseline, showcase=showcase)
