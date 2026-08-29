from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.core.enums import ScenarioType
from apps.api.app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class FeatureVersion(CreatedAtMixin, Base):
    __tablename__ = "feature_versions"

    version: Mapped[str] = mapped_column(String(100), primary_key=True)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    feature_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class ModelVersion(CreatedAtMixin, Base):
    __tablename__ = "model_versions"

    version: Mapped[str] = mapped_column(String(100), primary_key=True)
    model_type: Mapped[str] = mapped_column(String(100), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    feature_version: Mapped[str] = mapped_column(
        String(100), ForeignKey("feature_versions.version"), nullable=False
    )
    training_dataset_version: Mapped[str] = mapped_column(
        String(100), ForeignKey("dataset_versions.version"), nullable=False
    )
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class DatasetVersion(CreatedAtMixin, Base):
    __tablename__ = "dataset_versions"

    version: Mapped[str] = mapped_column(String(100), primary_key=True)
    generator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    legitimate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    abuse_count: Mapped[int] = mapped_column(Integer, nullable=False)


class ScenarioRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "scenario_runs"

    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scenario_type: Mapped[ScenarioType] = mapped_column(String(32), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
