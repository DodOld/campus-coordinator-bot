"""Focused persistence operations; PostgreSQL constraints provide idempotency."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import TopicPolicy
from app.models import AllCommandAudit, ChatSettings, ProcessedUpdate, VKProcessedPost, VKSource


class BotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sync_chat_policies(self, policies: dict[int, TopicPolicy]) -> None:
        for chat_id, policy in policies.items():
            statement = pg_insert(ChatSettings).values(
                chat_id=chat_id,
                enabled=True,
                debug_thread_id=policy.debug,
                posts_thread_id=policy.posts,
                schedule_thread_id=policy.schedule,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[ChatSettings.chat_id],
                set_={
                    "enabled": True,
                    "debug_thread_id": policy.debug,
                    "posts_thread_id": policy.posts,
                    "schedule_thread_id": policy.schedule,
                },
            )
            await self.session.execute(statement)

    async def claim_update(self, update_id: int) -> bool:
        statement = pg_insert(ProcessedUpdate).values(update_id=update_id).on_conflict_do_nothing()
        result = await self.session.execute(statement)
        return result.rowcount == 1

    async def claim_all_command(
        self,
        *,
        key: str,
        chat_id: int,
        source_thread_id: int | None,
        source_message_id: int,
        actor_id: int,
        requested_text: str,
    ) -> AllCommandAudit | None:
        audit = AllCommandAudit(
            idempotency_key=key,
            chat_id=chat_id,
            source_thread_id=source_thread_id,
            source_message_id=source_message_id,
            actor_id=actor_id,
            requested_text=requested_text,
        )
        self.session.add(audit)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return None
        return audit

    async def finish_all_command(self, audit: AllCommandAudit, recipient_count: int, message_id: int) -> None:
        audit.recipient_count = recipient_count
        audit.final_debug_message_id = message_id
        audit.status = "delivered"
        await self.session.flush()

    async def fail_all_command(self, audit: AllCommandAudit) -> None:
        audit.status = "failed"
        await self.session.flush()

    async def add_vk_source(self, source: VKSource) -> VKSource:
        self.session.add(source)
        await self.session.flush()
        return source

    async def list_vk_sources(self, chat_id: int) -> list[VKSource]:
        return list((await self.session.scalars(select(VKSource).where(VKSource.chat_id == chat_id).order_by(VKSource.id))).all())

    async def disable_vk_source(self, chat_id: int, source_id: int) -> bool:
        source = await self.session.get(VKSource, source_id)
        if source is None or source.chat_id != chat_id:
            return False
        source.enabled = False
        await self.session.flush()
        return True

    async def enabled_vk_sources(self) -> list[VKSource]:
        return list((await self.session.scalars(select(VKSource).where(VKSource.enabled.is_(True)))).all())

    async def claim_vk_post(self, source_id: int, post_id: int, post_datetime: datetime | None) -> VKProcessedPost | None:
        claim = VKProcessedPost(source_id=source_id, post_id=post_id, post_datetime=post_datetime)
        try:
            async with self.session.begin_nested():
                self.session.add(claim)
                await self.session.flush()
        except IntegrityError:
            return None
        return claim

    async def finish_vk_post(self, claim: VKProcessedPost, message_id: int) -> None:
        claim.status = "delivered"
        claim.delivered_message_id = message_id
        await self.session.flush()

    async def fail_vk_post(self, claim: VKProcessedPost) -> None:
        # At-most-once delivery deliberately wins over a duplicate after a restart.
        claim.status = "failed"
        await self.session.flush()

    async def mark_source_checked(self, source: VKSource, newest_post_id: int | None) -> None:
        source.last_checked_at = datetime.now(UTC)
        if newest_post_id is not None:
            source.last_seen_post_id = max(source.last_seen_post_id or 0, newest_post_id)
        await self.session.flush()
