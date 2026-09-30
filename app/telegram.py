"""Telegram-specific policy, formatting, and safe sending primitives."""

from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass
from typing import Protocol

from aiogram import Bot
from aiogram.types import MessageEntity, User

from app.config import TopicPolicy

MAX_MESSAGE_CHARS = 3800


class Sender(Protocol):
    async def send_message(self, **kwargs: object): ...


@dataclass(frozen=True, slots=True)
class MentionBatch:
    text: str
    entities: list[MessageEntity]


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def batch_mentions(users: list[User], max_chars: int = MAX_MESSAGE_CHARS) -> list[MentionBatch]:
    """Build Bot API ``text_mention`` batches without splitting an entity."""
    if max_chars < 8:
        raise ValueError("max_chars is too small")
    batches: list[MentionBatch] = []
    text_parts: list[str] = []
    entities: list[MessageEntity] = []
    text_len = 0
    utf16_offset = 0

    def flush() -> None:
        nonlocal text_parts, entities, text_len, utf16_offset
        if text_parts:
            batches.append(MentionBatch("".join(text_parts), entities))
        text_parts, entities, text_len, utf16_offset = [], [], 0, 0

    for user in users:
        display = (user.full_name or str(user.id)).replace("\n", " ").strip()[:128]
        token = f"{display}\n"
        if text_parts and text_len + len(token) > max_chars:
            flush()
        # A pathological display name cannot make the entire message invalid.
        if len(token) > max_chars:
            display = display[: max_chars - 1]
            token = f"{display}\n"
        entities.append(MessageEntity(type="text_mention", offset=utf16_offset, length=utf16_length(display), user=user))
        text_parts.append(token)
        text_len += len(token)
        utf16_offset += utf16_length(token)
    flush()
    return batches


def build_message_link(chat_id: int, message_id: int, chat_username: str | None) -> str | None:
    """Create a canonical link without guessing IDs for legacy basic groups."""
    if chat_username:
        return f"https://t.me/{chat_username}/{message_id}"
    text_id = str(chat_id)
    if text_id.startswith("-100"):
        return f"https://t.me/c/{text_id[4:]}/{message_id}"
    return None


class TopicMessenger:
    def __init__(self, bot: Bot, policies: dict[int, TopicPolicy]) -> None:
        self.bot = bot
        self.policies = policies

    def policy_for(self, chat_id: int) -> TopicPolicy | None:
        return self.policies.get(chat_id)

    async def send_debug(self, chat_id: int, text: str, **kwargs: object):
        policy = self.policies.get(chat_id)
        if policy is None:
            return None
        return await self.bot.send_message(
            chat_id=chat_id,
            message_thread_id=policy.debug,
            text=text,
            **kwargs,
        )

    async def send_to_allowed_topic(self, chat_id: int, thread_id: int, text: str, **kwargs: object):
        policy = self.policies.get(chat_id)
        if policy is None or not policy.allows_vk_target(thread_id):
            raise ValueError("target thread is not an allowed bot output topic")
        return await self.bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=text,
            **kwargs,
        )

    async def safe_debug_error(self, chat_id: int, area: str) -> None:
        """Notify operators without serializing exception text or sensitive context."""
        try:
            await self.send_debug(chat_id, f"⚠️ Сбой задачи: {html.escape(area)}. Повторите позже.")
        except Exception:
            # Logging is handled by the caller; Debug reporting must never crash a handler.
            return


async def eligible_group_members(bot: Bot, chat_id: int, user_ids: tuple[int, ...]) -> list[User]:
    semaphore = asyncio.Semaphore(8)

    async def resolve(user_id: int) -> User | None:
        async with semaphore:
            member = await bot.get_chat_member(chat_id, user_id)
        status = str(member.status)
        is_member = getattr(member, "is_member", True)
        if status not in {"member", "administrator", "creator", "owner", "restricted"} or not is_member:
            return None
        user = member.user
        if user.is_bot or getattr(user, "is_deleted", False):
            return None
        return user

    results = await asyncio.gather(*(resolve(user_id) for user_id in user_ids), return_exceptions=True)
    # Individual unavailable IDs are skipped: one departed user must not block a notification.
    return [result for result in results if isinstance(result, User)]
