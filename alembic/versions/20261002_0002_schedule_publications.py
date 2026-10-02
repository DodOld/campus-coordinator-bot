"""Add idempotency state for daily schedule publications.

Revision ID: 20261002_0002
Revises: 20260930_0001
Create Date: 2026-10-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20261002_0002"
down_revision = "20260930_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_publications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("schedule_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="claimed"),
        sa.Column("delivered_message_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("chat_id", "schedule_date", name="uq_schedule_publication_date"),
    )


def downgrade() -> None:
    op.drop_table("schedule_publications")
