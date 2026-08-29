import math
from datetime import datetime

from apps.api.app.core.enums import TransactionStatus
from apps.api.app.schemas.contracts import RawPaymentEvent
from packages.synthetic.config import GenerationConfig
from packages.synthetic.domain import (
    AddressIdentity,
    CustomerIdentity,
    DeviceIdentity,
    GeneratedEvent,
    InstrumentIdentity,
    MerchantIdentity,
    NetworkIdentity,
    SyntheticGroundTruth,
)
from packages.synthetic.rng import RandomStream


def sample_amount(
    rng: RandomStream,
    config: GenerationConfig,
    category: str,
    *,
    scale: float = 1.0,
) -> int:
    median = config.behavior.merchant_median_paise[category] * scale
    amount = int(rng.lognormal(math.log(max(median, 1)), config.behavior.amount_lognormal_sigma))
    return max(config.behavior.amount_min_paise, min(amount, config.behavior.amount_max_paise))


def build_event(
    *,
    event_id: str,
    event_time: datetime,
    customer: CustomerIdentity,
    device: DeviceIdentity,
    instrument: InstrumentIdentity,
    network: NetworkIdentity,
    address: AddressIdentity,
    merchant: MerchantIdentity,
    amount_paise: int,
    failed: bool,
    truth: SyntheticGroundTruth,
) -> GeneratedEvent:
    status = TransactionStatus.FAILED if failed else TransactionStatus.AUTHORIZED
    facts = RawPaymentEvent(
        event_id=event_id,
        event_time=event_time,
        customer_ref=customer.ref,
        account_created_at=customer.account_created_at,
        customer_segment=customer.segment,
        home_region=customer.home_region,
        instrument_fingerprint=instrument.fingerprint,
        instrument_type=instrument.instrument_type,
        issuer_region=instrument.issuer_region,
        device_fingerprint=device.fingerprint,
        device_type=device.device_type,
        os_family=device.os_family,
        browser_family=device.browser_family,
        ip_hash=network.ip_hash,
        network_type=network.network_type,
        ip_region=network.region,
        address_fingerprint=address.fingerprint,
        address_region=address.region,
        postal_prefix=address.postal_prefix,
        merchant_ref=merchant.ref,
        merchant_category=merchant.category,
        merchant_region=merchant.region,
        merchant_risk_baseline=merchant.risk_baseline,
        amount_paise=amount_paise,
        payment_method=instrument.instrument_type,
        status=status,
        failure_code="SYNTHETIC_DECLINE" if failed else None,
    )
    return GeneratedEvent(facts=facts, truth=truth)
