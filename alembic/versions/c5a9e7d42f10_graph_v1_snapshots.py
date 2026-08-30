"""graph v1 snapshots

Revision ID: c5a9e7d42f10
Revises: 8b73f4a91c2e
Create Date: 2026-08-30 07:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c5a9e7d42f10"
down_revision: str | None = "8b73f4a91c2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("abuse_clusters", sa.Column("fingerprint", sa.String(64), nullable=True))
    op.execute("UPDATE abuse_clusters SET fingerprint = id::text WHERE fingerprint IS NULL")
    op.alter_column("abuse_clusters", "fingerprint", nullable=False)
    op.create_unique_constraint(
        "uq_abuse_clusters_fingerprint",
        "abuse_clusters",
        ["fingerprint"],
    )
    op.create_unique_constraint(
        "uq_cluster_members_cluster_entity",
        "cluster_members",
        ["cluster_id", "entity_type", "entity_public_id"],
    )
    op.create_table(
        "graph_assessment_snapshots",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("graph_version", sa.String(100), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("structural_score", sa.Float(), nullable=False),
        sa.Column(
            "component_fingerprints",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("candidate_cluster", sa.Boolean(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_source_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_graph_assessment_snapshots_transaction_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_assessment_snapshots")),
        sa.UniqueConstraint(
            "transaction_id",
            "graph_version",
            name="uq_graph_assessments_transaction_version",
        ),
    )
    op.create_index(
        "ix_graph_assessments_version_transaction",
        "graph_assessment_snapshots",
        ["graph_version", "transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_graph_assessments_version_transaction",
        table_name="graph_assessment_snapshots",
    )
    op.drop_table("graph_assessment_snapshots")
    op.drop_constraint(
        "uq_cluster_members_cluster_entity",
        "cluster_members",
        type_="unique",
    )
    op.drop_constraint(
        "uq_abuse_clusters_fingerprint",
        "abuse_clusters",
        type_="unique",
    )
    op.drop_column("abuse_clusters", "fingerprint")
