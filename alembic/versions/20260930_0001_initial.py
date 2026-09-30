"""Initial coordinator bot schema.

Revision ID: 20260930_0001
Revises:
Create Date: 2026-09-30
"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_settings",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("debug_thread_id", sa.BigInteger()),
        sa.Column("posts_thread_id", sa.BigInteger()),
        sa.Column("schedule_thread_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "processed_updates",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "all_command_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_thread_id", sa.BigInteger()),
        sa.Column("source_message_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="claimed"),
        sa.Column("final_debug_message_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "vk_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("canonical_url", sa.String(length=1024), nullable=False),
        sa.Column("target_thread_id", sa.BigInteger(), nullable=False),
        sa.Column("preview_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("last_seen_post_id", sa.BigInteger()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("chat_id", "owner_id", "target_thread_id", name="uq_vk_source_target"),
    )
    op.create_index("ix_vk_sources_chat_id", "vk_sources", ["chat_id"])
    op.create_table(
        "vk_processed_posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("vk_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("post_datetime", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="claimed"),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("delivered_message_id", sa.BigInteger()),
        sa.UniqueConstraint("source_id", "post_id", name="uq_vk_processed_post"),
    )


def downgrade() -> None:
    op.drop_table("vk_processed_posts")
    op.drop_index("ix_vk_sources_chat_id", table_name="vk_sources")
    op.drop_table("vk_sources")
    op.drop_table("all_command_audit")
    op.drop_table("processed_updates")
    op.drop_table("chat_settings")
