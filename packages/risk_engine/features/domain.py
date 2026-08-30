from dataclasses import dataclass
from datetime import datetime

from apps.api.app.core.enums import TransactionStatus


@dataclass(frozen=True, slots=True)
class ScoringFeatureTransaction:
    transaction_public_id: str
    customer_id: str
    merchant_id: str
    instrument_id: str
    device_id: str
    ip_id: str
    address_id: str
    amount_paise: int
    currency: str
    payment_method: str
    event_time: datetime
    account_created_at: datetime


@dataclass(frozen=True, slots=True)
class FeatureTransaction(ScoringFeatureTransaction):
    status: TransactionStatus
    failure_code: str | None = None

    def scoring_context(self) -> ScoringFeatureTransaction:
        values = {
            field: getattr(self, field) for field in ScoringFeatureTransaction.__dataclass_fields__
        }
        return ScoringFeatureTransaction(**values)


@dataclass(frozen=True, slots=True)
class TrainingExample:
    transaction_public_id: str
    features: dict[str, float | int | bool]
    label: str
    scenario: str
    ring_id: str | None
