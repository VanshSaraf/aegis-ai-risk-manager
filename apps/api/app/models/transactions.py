import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.core.enums import GroundTruthLabel, ScenarioType, TransactionStatus
from apps.api.app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Transaction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_customer_event_time", "customer_id", "event_time"),
        Index("ix_transactions_device_event_time", "device_id", "event_time"),
        Index("ix_transactions_instrument_event_time", "payment_instrument_id", "event_time"),
        Index("ix_transactions_ip_event_time", "ip_address_id", "event_time"),
        Index("ix_transactions_address_event_time", "address_id", "event_time"),
        Index("ix_transactions_merchant_event_time", "merchant_id", "event_time"),
    )

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    payment_instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_instruments.id"), nullable=False
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False
    )
    ip_address_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ip_addresses.id"), nullable=False
    )
    address_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("addresses.id"), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scenario_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_runs.id"), nullable=True
    )
    ground_truth_label: Mapped[GroundTruthLabel | None] = mapped_column(String(32), nullable=True)
    ground_truth_scenario: Mapped[ScenarioType | None] = mapped_column(String(32), nullable=True)
    ground_truth_ring_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
