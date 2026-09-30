"""Official VK API client and idempotent public-wall monitor."""

from __future__ import annotations

import asyncio
import html
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp
import structlog
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import VKProcessedPost, VKSource
from app.repositories import BotRepository
from app.telegram import TopicMessenger

log = structlog.get_logger(__name__)
VK_API_BASE_URL = "https://api.vk.ru/method"
VK_WEB_BASE_URL = "https://vk.ru"
_COMMUNITY = re.compile(r"^(?:(?:https?://)?(?:www\.)?vk\.(?:ru|com)/)?([A-Za-z0-9_.-]+)$", re.IGNORECASE)


class VKAPIError(RuntimeError):
    def __init__(self, code: int, safe_message: str, retry_after: float | None = None) -> None:
        super().__init__(safe_message)
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class VKCommunity:
    owner_id: int
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class VKWallPost:
    post_id: int
    published_at: datetime
    text: str
    url: str


class VKAPIClient:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings) -> None:
        self.session = session
        self.token = settings.vk_api_token.get_secret_value()
        self.version = settings.vk_api_version

    async def _call(self, method: str, **params: object) -> Any:
        payload = {"access_token": self.token, "v": self.version, **params}
        async with self.session.post(f"{VK_API_BASE_URL}/{method}", data=payload) as response:
            response.raise_for_status()
            data: dict[str, Any] = await response.json(content_type=None)
        error = data.get("error")
        if error:
            code = int(error.get("error_code", 0))
            # VK error text may contain untrusted input; never surface it to Telegram/logs.
            retry_after = 1.0 if code in {6, 9, 10, 29} else None
            raise VKAPIError(code, f"VK API error {code or 'unknown'}", retry_after)
        response_data = data.get("response")
        if response_data is None:
            raise VKAPIError(0, "Malformed VK API response")
        return response_data

    async def resolve_public_community(self, value: str) -> VKCommunity:
        match = _COMMUNITY.fullmatch(value.strip())
        if match is None:
            raise ValueError("Укажите публичный shortname или ссылку vk.ru")
        screen_name = match.group(1)
        # ``utils.resolveScreenName`` returns error 1051 for current VK service
        # tokens, even though ``groups.getById`` is available.  The latter accepts
        # a public screen name directly and confirms that it belongs to a group.
        groups = await self._call("groups.getById", group_ids=screen_name)
        if isinstance(groups, list):
            items = groups
        elif isinstance(groups, dict):
            items = groups.get("groups", groups.get("items", []))
        else:
            items = []
        if not isinstance(items, list) or not items:
            raise VKAPIError(0, "VK group metadata unavailable")
        group = items[0]
        if not isinstance(group, dict):
            raise VKAPIError(0, "Malformed VK group metadata")
        if not isinstance(group.get("id"), int):
            raise ValueError("Указанный адрес не является публичным VK-сообществом")
        group_id = int(group["id"])
        actual_screen_name = str(group.get("screen_name") or screen_name)
        return VKCommunity(
            owner_id=-group_id,
            title=str(group.get("name") or actual_screen_name),
            url=f"{VK_WEB_BASE_URL}/{actual_screen_name}",
        )

    async def wall_posts(self, owner_id: int, count: int = 20) -> list[VKWallPost]:
        response = await self._call("wall.get", owner_id=owner_id, count=count, filter="owner")
        if not isinstance(response, dict):
            raise VKAPIError(0, "Malformed VK wall response")
        items = response.get("items", [])
        if not isinstance(items, list):
            raise VKAPIError(0, "Malformed VK wall response")
        result: list[VKWallPost] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                continue
            post_id = int(item["id"])
            result.append(
                VKWallPost(
                    post_id=post_id,
                    published_at=datetime.fromtimestamp(int(item.get("date", 0)), tz=UTC),
                    text=str(item.get("text") or ""),
                    url=f"{VK_WEB_BASE_URL}/wall{owner_id}_{post_id}",
                )
            )
        return result


async def with_vk_retries(operation, attempts: int = 4):
    for attempt in range(attempts):
        try:
            return await operation()
        except (TimeoutError, aiohttp.ClientError, VKAPIError) as error:
            retry_after = error.retry_after if isinstance(error, VKAPIError) else None
            is_transient = not isinstance(error, VKAPIError) or retry_after is not None or error.code >= 500
            if not is_transient or attempt == attempts - 1:
                raise
            delay = retry_after if retry_after is not None else min(30.0, 2**attempt + random.random())
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


def safe_excerpt(text: str, limit: int = 320) -> str:
    normalized = " ".join(text.split())
    return normalized[:limit].rstrip() + ("…" if len(normalized) > limit else "")


class VKMonitor:
    def __init__(
        self,
        client: VKAPIClient,
        sessions: async_sessionmaker[AsyncSession],
        messenger: TopicMessenger,
        settings: Settings,
    ) -> None:
        self.client = client
        self.sessions = sessions
        self.messenger = messenger
        self.settings = settings

    async def add_source(self, chat_id: int, community_input: str, target_thread_id: int, preview: bool) -> VKSource:
        policy = self.messenger.policy_for(chat_id)
        if policy is None or not policy.allows_vk_target(target_thread_id):
            raise ValueError("Источник можно направить только в настроенную тему Posts или Schedule")
        community = await with_vk_retries(lambda: self.client.resolve_public_community(community_input))
        latest = await with_vk_retries(lambda: self.client.wall_posts(community.owner_id, count=1))
        async with self.sessions() as session:
            source = VKSource(
                chat_id=chat_id,
                owner_id=community.owner_id,
                title=community.title,
                canonical_url=community.url,
                target_thread_id=target_thread_id,
                preview_enabled=preview,
                poll_interval_seconds=self.settings.vk_poll_interval_seconds,
                last_seen_post_id=latest[0].post_id if latest else None,
            )
            await BotRepository(session).add_vk_source(source)
            await session.commit()
            return source

    async def poll_once(self) -> None:
        async with self.sessions() as session:
            sources = await BotRepository(session).enabled_vk_sources()
        for source in sources:
            try:
                await self._poll_source(source)
            except Exception:
                log.exception("vk_source_poll_failed", source_id=source.id, chat_id=source.chat_id)
                await self.messenger.safe_debug_error(source.chat_id, "Мониторинг VK-сообщества")

    async def _poll_source(self, source: VKSource) -> None:
        if source.last_checked_at is not None:
            elapsed = (datetime.now(UTC) - source.last_checked_at).total_seconds()
            if elapsed < source.poll_interval_seconds:
                return
        posts = await with_vk_retries(lambda: self.client.wall_posts(source.owner_id))
        new_posts = sorted((post for post in posts if post.post_id > (source.last_seen_post_id or 0)), key=lambda p: p.post_id)
        for post in new_posts:
            claim = await self._claim(source.id, post)
            if claim is None:
                continue
            try:
                excerpt = safe_excerpt(post.text) if source.preview_enabled else ""
                preview_text = f"\n\n{html.escape(excerpt)}" if excerpt else ""
                sent = await self.messenger.send_to_allowed_topic(
                    source.chat_id,
                    source.target_thread_id,
                    f'Новая публикация: <b>{html.escape(source.title)}</b>{preview_text}\n\n<a href="{post.url}">Открыть оригинал</a>',
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=not source.preview_enabled,
                )
                await self._finish_claim(claim.id, sent.message_id)
            except Exception:
                log.exception("vk_post_delivery_failed", source_id=source.id, post_id=post.post_id)
                await self._fail_claim(claim.id)
                await self.messenger.safe_debug_error(source.chat_id, "Публикация VK")
        newest = max((post.post_id for post in posts), default=None)
        async with self.sessions() as session:
            current = await session.get(VKSource, source.id)
            if current is not None:
                await BotRepository(session).mark_source_checked(current, newest)
                await session.commit()

    async def _claim(self, source_id: int, post: VKWallPost) -> VKProcessedPost | None:
        async with self.sessions() as session:
            claim = await BotRepository(session).claim_vk_post(source_id, post.post_id, post.published_at)
            if claim is not None:
                await session.commit()
                return claim
            return None

    async def _finish_claim(self, claim_id: int, message_id: int) -> None:
        async with self.sessions() as session:
            claim = await session.get(VKProcessedPost, claim_id)
            if claim is not None:
                await BotRepository(session).finish_vk_post(claim, message_id)
                await session.commit()

    async def _fail_claim(self, claim_id: int) -> None:
        async with self.sessions() as session:
            claim = await session.get(VKProcessedPost, claim_id)
            if claim is not None:
                await BotRepository(session).fail_vk_post(claim)
                await session.commit()
