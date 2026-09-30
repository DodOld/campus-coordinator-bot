"""Aiogram routers. All group policy checks happen before command work."""

from __future__ import annotations

import shlex

import structlog
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.all_service import AllService
from app.repositories import BotRepository
from app.telegram import TopicMessenger
from app.vk import VKMonitor

log = structlog.get_logger(__name__)


def build_router(
    all_service: AllService,
    vk_monitor: VKMonitor,
    messenger: TopicMessenger,
    sessions: async_sessionmaker[AsyncSession],
) -> Router:
    router = Router(name="group_commands")

    @router.message(F.text.regexp(r"^!all(?:\s|$)"))
    async def all_command(message: Message) -> None:
        if not is_allowed_group(message, messenger):
            return
        await all_service.execute(message)

    @router.message(F.text.regexp(r"^!vk(?:\s|$)"))
    async def vk_command(message: Message, bot: Bot) -> None:
        if not is_allowed_group(message, messenger) or not _is_debug_message(message, messenger):
            return
        if message.from_user is None or not await _is_admin(bot, message.chat.id, message.from_user.id):
            return
        try:
            arguments = shlex.split((message.text or "")[len("!vk") :])
            if not arguments:
                raise ValueError("Используйте !vk add, !vk list или !vk remove")
            action = arguments.pop(0).lower()
            if action == "add":
                await _vk_add(message, arguments, vk_monitor, messenger)
            elif action == "list":
                await _vk_list(message, sessions, messenger)
            elif action == "remove":
                await _vk_remove(message, arguments, sessions, messenger)
            else:
                raise ValueError("Неизвестная команда VK")
        except ValueError as error:
            await messenger.send_debug(message.chat.id, f"⚠️ {error}")
        except Exception:
            log.exception("vk_admin_command_failed", chat_id=message.chat.id)
            await messenger.safe_debug_error(message.chat.id, "Настройка источника VK")

    return router


def is_allowed_group(message: Message, messenger: TopicMessenger) -> bool:
    """Private messages and every unconfigured chat are intentionally silent."""
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP} and messenger.policy_for(message.chat.id) is not None


def _is_debug_message(message: Message, messenger: TopicMessenger) -> bool:
    policy = messenger.policy_for(message.chat.id)
    return policy is not None and message.message_thread_id == policy.debug


async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return str(member.status) in {"administrator", "creator", "owner"}


async def _vk_add(message: Message, args: list[str], monitor: VKMonitor, messenger: TopicMessenger) -> None:
    if len(args) not in {2, 3}:
        raise ValueError("Формат: !vk add <community> <topic_id> [preview]")
    preview = len(args) == 3 and args[2].lower() == "preview"
    if len(args) == 3 and not preview:
        raise ValueError("Третий параметр может быть только preview")
    source = await monitor.add_source(message.chat.id, args[0], int(args[1]), preview)
    await messenger.send_debug(message.chat.id, f"✅ Добавлен VK-источник #{source.id}: {source.title}")


async def _vk_list(message: Message, sessions: async_sessionmaker[AsyncSession], messenger: TopicMessenger) -> None:
    async with sessions() as session:
        sources = await BotRepository(session).list_vk_sources(message.chat.id)
    if not sources:
        await messenger.send_debug(message.chat.id, "VK-источники не настроены.")
        return
    lines = [
        f"#{source.id} · {source.title} · тема {source.target_thread_id} · {'вкл.' if source.enabled else 'выкл.'}" for source in sources
    ]
    await messenger.send_debug(message.chat.id, "\n".join(lines))


async def _vk_remove(message: Message, args: list[str], sessions: async_sessionmaker[AsyncSession], messenger: TopicMessenger) -> None:
    if len(args) != 1:
        raise ValueError("Формат: !vk remove <id>")
    async with sessions() as session:
        removed = await BotRepository(session).disable_vk_source(message.chat.id, int(args[0]))
        await session.commit()
    await messenger.send_debug(message.chat.id, "✅ Источник отключён." if removed else "Источник не найден.")
