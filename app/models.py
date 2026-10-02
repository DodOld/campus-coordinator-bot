"""Database entities. Time is always persisted in UTC."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ChatSettings(Base):
    __tablename__ = "chat_settings"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    debug_thread_id: Mapped[int | None] = mapped_column(BigInteger)
    posts_thread_id: Mapped[int | None] = mapped_column(BigInteger)
    schedule_thread_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AllCommandAudit(Base):
    __tablename__ = "all_command_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_thread_id: Mapped[int | None] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requested_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="claimed", nullable=False)
    final_debug_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VKSource(Base):
    __tablename__ = "vk_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    target_thread_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    preview_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    last_seen_post_id: Mapped[int | None] = mapped_column(BigInteger)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_posts: Mapped[list[VKProcessedPost]] = relationship(back_populates="source")

    __table_args__ = (UniqueConstraint("chat_id", "owner_id", "target_thread_id", name="uq_vk_source_target"),)


class VKProcessedPost(Base):
    __tablename__ = "vk_processed_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("vk_sources.id", ondelete="CASCADE"), nullable=False)
    post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    post_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="claimed", nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_message_id: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[VKSource] = relationship(back_populates="processed_posts")

    __table_args__ = (UniqueConstraint("source_id", "post_id", name="uq_vk_processed_post"),)


class SchedulePublication(Base):
    __tablename__ = "schedule_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schedule_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="claimed", nullable=False)
    delivered_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("chat_id", "schedule_date", name="uq_schedule_publication_date"),)
