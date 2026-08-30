from datetime import UTC, datetime
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.api.app.core.enums import (
    NetworkType,
    PolicyAction,
    RiskSeverity,
    TransactionStatus,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawPaymentEvent(StrictModel):
    event_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(default="payment.transaction", min_length=1, max_length=100)
    event_version: str = Field(default="1.0", min_length=1, max_length=32)
    event_time: datetime
    received_at: datetime | None = None
    customer_ref: str = Field(min_length=1, max_length=255)
    account_created_at: datetime
    customer_segment: str = Field(min_length=1, max_length=100)
    home_region: str = Field(min_length=1, max_length=100)
    instrument_fingerprint: str = Field(min_length=1, max_length=255)
    instrument_type: str = Field(min_length=1, max_length=50)
    issuer_region: str = Field(min_length=1, max_length=100)
    device_fingerprint: str = Field(min_length=1, max_length=255)
    device_type: str = Field(min_length=1, max_length=50)
    os_family: str = Field(min_length=1, max_length=50)
    browser_family: str = Field(min_length=1, max_length=50)
    ip_hash: str = Field(min_length=1, max_length=255)
    network_type: NetworkType
    ip_region: str = Field(min_length=1, max_length=100)
    address_fingerprint: str = Field(min_length=1, max_length=255)
    address_region: str = Field(min_length=1, max_length=100)
    postal_prefix: str = Field(min_length=1, max_length=20)
    merchant_ref: str = Field(min_length=1, max_length=255)
    merchant_category: str = Field(min_length=1, max_length=100)
    merchant_region: str = Field(min_length=1, max_length=100)
    merchant_risk_baseline: float = Field(ge=0, le=1)
    amount_paise: Annotated[int, Field(gt=0, strict=True)]
    currency: str = Field(default="INR", min_length=3, max_length=3)
    payment_method: str = Field(min_length=1, max_length=50)
    status: TransactionStatus
    failure_code: str | None = Field(default=None, max_length=100)

    @field_validator("event_time", "received_at", "account_created_at")
    @classmethod
    def timestamps_are_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC) if value is not None else None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("currency must be a three-letter ISO-style code")
        return value.upper()

    @model_validator(mode="after")
    def failure_status_has_code(self) -> Self:
        if self.status == TransactionStatus.FAILED and not self.failure_code:
            raise ValueError("failure_code is required for failed transactions")
        return self


class ScoringTransaction(StrictModel):
    """Runtime-safe transaction input; intentionally contains no ground truth."""

    transaction_public_id: str
    customer_public_id: str
    merchant_public_id: str
    payment_instrument_public_id: str
    device_public_id: str
    ip_address_public_id: str
    address_public_id: str
    amount_paise: Annotated[int, Field(gt=0, strict=True)]
    currency: str
    payment_method: str
    event_time: datetime


class NormalizedTransaction(ScoringTransaction):
    status: TransactionStatus
    failure_code: str | None
    received_at: datetime
    processed_at: datetime | None
    created_at: datetime


class FeatureVector(StrictModel):
    transaction_public_id: str
    feature_version: str
    values: dict[str, float | int | bool]
    computed_at: datetime
    max_source_event_time: datetime | None


class ModelPrediction(StrictModel):
    transaction_public_id: str
    model_version: str
    feature_version: str
    ml_score: float = Field(ge=0, le=1)
    top_features: list[dict[str, Any]] = Field(default_factory=list)
    inference_latency_ms: int = Field(ge=0)


class RiskAssessment(StrictModel):
    transaction_public_id: str
    model_version: str
    feature_version: str
    graph_version: str
    model_score: float = Field(ge=0, le=1)
    graph_structure_score: float = Field(ge=0, le=1)
    severity: RiskSeverity
    graph_signals: list[dict[str, Any]] = Field(default_factory=list)
    detected_cluster_id: str | None = None
    rule_signals: list[str] = Field(default_factory=list)
    policy_context: dict[str, Any]
    computed_at: datetime


class PolicyDecisionResult(StrictModel):
    decision_public_id: str
    transaction_public_id: str
    policy_version: str
    action: PolicyAction
    severity: RiskSeverity
    reason_codes: list[str]
    requires_human_review: bool
    created_at: datetime
