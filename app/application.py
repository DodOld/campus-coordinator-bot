"""Process composition, health endpoint, and graceful async lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import aiohttp
import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiohttp import web
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.all_service import AllService
from app.config import Settings
from app.db import create_engine, create_session_factory
from app.handlers import build_router
from app.logging import configure_logging
from app.repositories import BotRepository
from app.schedule import GoBinaryScheduleProvider
from app.schedule_service import ScheduleService, schedule_loop
from app.telegram import TopicMessenger
from app.vk import VKAPIClient, VKMonitor

log = structlog.get_logger(__name__)


class UpdateIdempotencyMiddleware(BaseMiddleware):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        update = data.get("event_update")
        if update is None:
            return await handler(event, data)
        async with self.sessions() as session:
            claimed = await BotRepository(session).claim_update(update.update_id)
            await session.commit()
        if not claimed:
            return None
        return await handler(event, data)


async def _health(_: web.Request) -> web.Response:
    engine: AsyncEngine = _.app["engine"]
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return web.json_response({"status": "unhealthy"}, status=503)
    return web.json_response({"status": "ok"})


async def start_health_server(engine: AsyncEngine, host: str, port: int) -> web.AppRunner:
    app = web.Application()
    app["engine"] = engine
    app.router.add_get("/healthz", _health)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner


async def vk_loop(monitor: VKMonitor, interval_seconds: int) -> None:
    while True:
        await monitor.poll_once()
        await asyncio.sleep(interval_seconds)


async def run(settings: Settings) -> None:
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    async with sessions() as session:
        await BotRepository(session).sync_chat_policies(settings.topic_policies)
        await session.commit()

    health = await start_health_server(engine, settings.http_host, settings.http_port)
    proxy_url = settings.telegram_proxy_url.get_secret_value() if settings.telegram_proxy_url else None
    bot = Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=None),
        session=AiohttpSession(proxy=proxy_url),
    )
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http_session:
        messenger = TopicMessenger(bot, settings.topic_policies)
        vk_monitor = VKMonitor(VKAPIClient(http_session, settings), sessions, messenger, settings)
        schedule_service = ScheduleService(
            GoBinaryScheduleProvider(settings.go_schedule_binary, settings.go_schedule_timeout_seconds), sessions, messenger
        )
        dispatcher = Dispatcher()
        dispatcher.update.outer_middleware(UpdateIdempotencyMiddleware(sessions))
        dispatcher.include_router(
            build_router(AllService(bot, settings, sessions, messenger), vk_monitor, schedule_service, messenger, sessions)
        )
        vk_job = asyncio.create_task(vk_loop(vk_monitor, settings.vk_poll_interval_seconds), name="vk-monitor")
        schedule_job = asyncio.create_task(schedule_loop(schedule_service), name="schedule-publisher")
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
        finally:
            for job in (vk_job, schedule_job):
                job.cancel()
            for job in (vk_job, schedule_job):
                with suppress(asyncio.CancelledError):
                    await job
            await health.cleanup()
            await bot.session.close()
            await engine.dispose()


def main() -> None:
    asyncio.run(run(Settings()))
