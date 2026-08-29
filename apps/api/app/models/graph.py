from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EntityEdge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_public_id",
            "relation_type",
            "target_type",
            "target_public_id",
            name="uq_entity_edges_logical_edge",
        ),
        Index("ix_entity_edges_source_lookup", "source_type", "source_public_id"),
        Index("ix_entity_edges_target_lookup", "target_type", "target_public_id"),
    )

    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
