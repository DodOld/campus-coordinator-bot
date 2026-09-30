from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, VKSource
from app.repositories import BotRepository
from app.vk import (
    _COMMUNITY,
    VK_API_BASE_URL,
    VK_WEB_BASE_URL,
    VKAPIClient,
    VKAPIError,
    safe_excerpt,
    with_vk_retries,
)


@pytest.mark.asyncio
async def test_vk_post_claim_is_deduplicated() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        source = VKSource(
            chat_id=-1001,
            owner_id=-1,
            title="Общество",
            canonical_url="https://vk.ru/example",
            target_thread_id=2,
            poll_interval_seconds=60,
        )
        session.add(source)
        await session.commit()
        source_id = source.id
    async with sessions() as session:
        first = await BotRepository(session).claim_vk_post(source_id, 101, datetime.now(UTC))
        assert first is not None
        await session.commit()
    async with sessions() as session:
        duplicate = await BotRepository(session).claim_vk_post(source_id, 101, datetime.now(UTC))
        assert duplicate is None
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_vk_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise VKAPIError(6, "rate limited", retry_after=0)
        return "ok"

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.vk.asyncio.sleep", no_sleep)
    assert await with_vk_retries(operation) == "ok"
    assert attempts == 2


def test_safe_excerpt_strips_whitespace_and_limits_size() -> None:
    assert safe_excerpt(" one\n two ") == "one two"
    assert safe_excerpt("abcdef", limit=4) == "abcd…"


def test_vk_ru_is_the_primary_endpoint_and_both_public_domains_are_accepted() -> None:
    assert VK_API_BASE_URL == "https://api.vk.ru/method"
    assert VK_WEB_BASE_URL == "https://vk.ru"
    assert _COMMUNITY.fullmatch("ic_tpu").group(1) == "ic_tpu"
    assert _COMMUNITY.fullmatch("https://vk.ru/ic_tpu").group(1) == "ic_tpu"
    assert _COMMUNITY.fullmatch("https://vk.com/ic_tpu").group(1) == "ic_tpu"


@pytest.mark.asyncio
async def test_resolve_community_uses_groups_get_by_id_with_shortname() -> None:
    client = object.__new__(VKAPIClient)
    calls: list[tuple[str, dict[str, object]]] = []

    async def call(method: str, **params: object) -> object:
        calls.append((method, params))
        return {"groups": [{"id": 42, "name": "TPU", "screen_name": "ic_tpu"}]}

    client._call = call  # type: ignore[method-assign]
    community = await client.resolve_public_community("https://vk.ru/ic_tpu")

    assert calls == [("groups.getById", {"group_ids": "ic_tpu"})]
    assert community.owner_id == -42
    assert community.url == "https://vk.ru/ic_tpu"
