"""Idempotent implementation of the group-only ``!all`` workflow."""

from __future__ import annotations

import html

import structlog
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import AllCommandAudit
from app.repositories import BotRepository
from app.telegram import TopicMessenger, batch_mentions, build_message_link, eligible_group_members

log = structlog.get_logger(__name__)


class AllService:
    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        messenger: TopicMessenger,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.sessions = sessions
        self.messenger = messenger

    async def execute(self, message: Message) -> None:
        if message.from_user is None:
            return
        chat_id = message.chat.id
        link = build_message_link(chat_id, message.message_id, message.chat.username)
        requested_text = (message.text or "")[len("!all") :].strip()
        key = f"all:{chat_id}:{message.message_id}"

        async with self.sessions() as session:
            repo = BotRepository(session)
            audit = await repo.claim_all_command(
                key=key,
                chat_id=chat_id,
                source_thread_id=message.message_thread_id,
                source_message_id=message.message_id,
                actor_id=message.from_user.id,
                requested_text=requested_text,
            )
            if audit is None:
                return
            await session.commit()

        if link is None:
            await self._fail(key, chat_id, "Невозможно создать безопасную ссылку на исходное сообщение")
            return

        try:
            members = await eligible_group_members(self.bot, chat_id, self.settings.member_ids)
            batches = batch_mentions(members)
            for batch in batches:
                await self.messenger.send_debug(chat_id, batch.text, entities=batch.entities)
            suffix = f"\n\n{html.escape(requested_text)}" if requested_text else ""
            final = await self.messenger.send_debug(
                chat_id,
                f'Вас упомянули в «<a href="{link}">ссылка</a>»{suffix}',
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            async with self.sessions() as session:
                audit = await session.scalar(select(AllCommandAudit).where(AllCommandAudit.idempotency_key == key))
                if audit is not None and final is not None:
                    await BotRepository(session).finish_all_command(audit, len(members), final.message_id)
                    await session.commit()
        except Exception:
            log.exception("all_command_failed", chat_id=chat_id, source_message_id=message.message_id)
            await self._fail(key, chat_id, "Не удалось обработать !all")

    async def _fail(self, key: str, chat_id: int, debug_text: str) -> None:
        async with self.sessions() as session:
            audit = await session.scalar(select(AllCommandAudit).where(AllCommandAudit.idempotency_key == key))
            if audit is not None:
                await BotRepository(session).fail_all_command(audit)
                await session.commit()
        await self.messenger.safe_debug_error(chat_id, debug_text)
