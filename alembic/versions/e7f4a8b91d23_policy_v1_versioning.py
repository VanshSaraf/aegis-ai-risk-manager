"""policy v1 versioning

Revision ID: e7f4a8b91d23
Revises: c5a9e7d42f10
Create Date: 2026-08-30 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7f4a8b91d23"
down_revision: str | None = "c5a9e7d42f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "risk_predictions",
        sa.Column("graph_version", sa.String(length=100), nullable=True),
    )
    op.execute("UPDATE risk_predictions SET graph_version = 'graph-v1'")
    op.alter_column("risk_predictions", "graph_version", nullable=False)
    op.alter_column("risk_predictions", "fused_score", existing_type=sa.Float(), nullable=True)
    op.alter_column("risk_predictions", "severity", existing_type=sa.String(32), nullable=True)
    op.create_unique_constraint(
        "uq_risk_predictions_transaction_model",
        "risk_predictions",
        ["transaction_id", "model_version"],
    )
    op.create_unique_constraint(
        "uq_risk_signals_transaction_code_rule",
        "risk_signals",
        ["transaction_id", "signal_code", "rule_version"],
    )
    op.create_unique_constraint(
        "uq_policy_decisions_transaction_policy",
        "policy_decisions",
        ["transaction_id", "policy_version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_policy_decisions_transaction_policy", "policy_decisions", type_="unique")
    op.drop_constraint("uq_risk_signals_transaction_code_rule", "risk_signals", type_="unique")
    op.drop_constraint("uq_risk_predictions_transaction_model", "risk_predictions", type_="unique")
    op.alter_column("risk_predictions", "severity", existing_type=sa.String(32), nullable=False)
    op.alter_column("risk_predictions", "fused_score", existing_type=sa.Float(), nullable=False)
    op.drop_column("risk_predictions", "graph_version")
