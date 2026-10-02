"""Telegram-facing schedule use cases and Tomsk-time daily publication."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import SchedulePublication
from app.repositories import BotRepository
from app.schedule import TOMSK_TIMEZONE, GoBinaryScheduleProvider, schedule_date_for_argument
from app.telegram import TopicMessenger

log = structlog.get_logger(__name__)


class ScheduleService:
    def __init__(
        self,
        provider: GoBinaryScheduleProvider,
        sessions: async_sessionmaker[AsyncSession],
        messenger: TopicMessenger,
    ) -> None:
        self.provider = provider
        self.sessions = sessions
        self.messenger = messenger

    async def publish_requested(self, chat_id: int, argument: str | None) -> None:
        try:
            target_date = schedule_date_for_argument(argument)
        except ValueError as error:
            await self.messenger.send_debug(chat_id, f"⚠️ {error}")
            return
        await self.messenger.send_debug(chat_id, f"⏳ Получаю расписание на {target_date:%d.%m.%Y}…")
        await self._fetch_and_publish(chat_id, target_date, daily=False)

    async def publish_daily(self, target_date: date) -> None:
        for chat_id, policy in self.messenger.policies.items():
            if policy.schedule is None:
                continue
            claim_id = await self._claim_daily(chat_id, target_date)
            if claim_id is None:
                continue
            await self._fetch_and_publish(chat_id, target_date, daily=True, claim_id=claim_id)

    async def _fetch_and_publish(self, chat_id: int, target_date: date, *, daily: bool, claim_id: int | None = None) -> None:
        result = await self.provider.render_for(target_date)
        if result.error:
            log.error("schedule_fetch_failed", chat_id=chat_id, daily=daily, reason=result.error)
            if claim_id is not None:
                await self._fail_daily(claim_id)
            await self.messenger.safe_debug_error(chat_id, "Получение расписания")
            return
        text = f"Расписание 0B62 на {target_date:%d.%m.%Y}\n\n{result.message}"
        try:
            messages = await self.messenger.send_schedule(chat_id, text)
            message_id = getattr(messages[-1], "message_id", None) if messages else None
            if message_id is None:
                raise RuntimeError("schedule topic is unavailable")
        except Exception:
            log.exception("schedule_delivery_failed", chat_id=chat_id, daily=daily)
            if claim_id is not None:
                await self._fail_daily(claim_id)
            await self.messenger.safe_debug_error(chat_id, "Публикация расписания")
            return
        if claim_id is not None:
            await self._finish_daily(claim_id, int(message_id))
        await self.messenger.send_debug(chat_id, f"✅ Расписание на {target_date:%d.%m.%Y} опубликовано в Schedule.")

    async def _claim_daily(self, chat_id: int, target_date: date) -> int | None:
        async with self.sessions() as session:
            publication = await BotRepository(session).claim_schedule_publication(chat_id, target_date)
            if publication is None:
                return None
            await session.commit()
            return publication.id

    async def _finish_daily(self, publication_id: int, message_id: int) -> None:
        async with self.sessions() as session:
            publication = await session.get(SchedulePublication, publication_id)
            if publication is not None:
                await BotRepository(session).finish_schedule_publication(publication, message_id)
                await session.commit()

    async def _fail_daily(self, publication_id: int) -> None:
        async with self.sessions() as session:
            publication = await session.get(SchedulePublication, publication_id)
            if publication is not None:
                await BotRepository(session).fail_schedule_publication(publication)
                await session.commit()


def seconds_until_tomsk_midnight(now: datetime | None = None) -> float:
    current = (now or datetime.now(TOMSK_TIMEZONE)).astimezone(TOMSK_TIMEZONE)
    next_midnight = datetime.combine(current.date() + timedelta(days=1), time.min, TOMSK_TIMEZONE)
    return max(0.0, (next_midnight - current).total_seconds())


async def schedule_loop(service: ScheduleService) -> None:
    while True:
        await asyncio.sleep(seconds_until_tomsk_midnight())
        try:
            await service.publish_daily(datetime.now(TOMSK_TIMEZONE).date())
        except Exception:
            log.exception("daily_schedule_loop_failed")
            await asyncio.sleep(60)
