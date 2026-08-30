"""version feature snapshots

Revision ID: 8b73f4a91c2e
Revises: 2d2145830235
Create Date: 2026-08-30 04:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8b73f4a91c2e"
down_revision: str | None = "2d2145830235"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_transaction_features_transaction_id",
        "transaction_features",
        type_="unique",
    )
    op.alter_column(
        "transaction_features",
        "max_source_event_time",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_transaction_features_transaction_version",
        "transaction_features",
        ["transaction_id", "feature_version"],
    )
    op.create_index(
        "ix_transaction_features_version_transaction",
        "transaction_features",
        ["feature_version", "transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_features_version_transaction",
        table_name="transaction_features",
    )
    op.drop_constraint(
        "uq_transaction_features_transaction_version",
        "transaction_features",
        type_="unique",
    )
    op.alter_column(
        "transaction_features",
        "max_source_event_time",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_transaction_features_transaction_id",
        "transaction_features",
        ["transaction_id"],
    )
