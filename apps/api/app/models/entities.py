from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.core.enums import NetworkType
from apps.api.app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    account_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    customer_segment: Mapped[str] = mapped_column(String(100), nullable=False)
    home_region: Mapped[str] = mapped_column(String(100), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=True)


class PaymentInstrument(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "payment_instruments"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(50), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    issuer_region: Mapped[str] = mapped_column(String(100), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Device(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "devices"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    device_fingerprint: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)
    os_family: Mapped[str] = mapped_column(String(50), nullable=False)
    browser_family: Mapped[str] = mapped_column(String(50), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IPAddress(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ip_addresses"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ip_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    network_type: Mapped[NetworkType] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Address(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "addresses"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    address_fingerprint: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    postal_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Merchant(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "merchants"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_baseline: Mapped[float] = mapped_column(Float, nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
