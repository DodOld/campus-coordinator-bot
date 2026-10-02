from types import SimpleNamespace

import pytest
from aiogram.enums import ChatType, ParseMode
from aiogram.types import User

from app.config import TopicPolicy
from app.handlers import HELP_TEXT, is_allowed_group, send_help
from app.telegram import TopicMessenger, batch_mentions, build_message_link, format_schedule_markdown, split_plaintext, utf16_length


def _user(identifier: int, name: str) -> User:
    return User(id=identifier, is_bot=False, first_name=name)


def test_mentions_are_batched_without_splitting_entities() -> None:
    users = [_user(1, "Алиса"), _user(2, "Bob 😀"), _user(3, "Чарли")]
    batches = batch_mentions(users, max_chars=12)

    assert [batch.text for batch in batches] == ["Алиса\nBob 😀\n", "Чарли\n"]
    assert [entity.user.id for batch in batches for entity in batch.entities] == [1, 2, 3]
    assert batches[0].entities[1].length == utf16_length("Bob 😀")


def test_message_link_uses_private_supergroup_canonical_form() -> None:
    assert build_message_link(-1001234567890, 55, None) == "https://t.me/c/1234567890/55"
    assert build_message_link(-987, 55, None) is None
    assert build_message_link(-100123, 55, "campus") == "https://t.me/campus/55"


def test_private_chat_is_not_allowed() -> None:
    messenger = TopicMessenger(SimpleNamespace(), {-1001: TopicPolicy(debug=1, posts=2, schedule=3)})
    private = SimpleNamespace(chat=SimpleNamespace(id=42, type=ChatType.PRIVATE))
    group = SimpleNamespace(chat=SimpleNamespace(id=-1001, type=ChatType.SUPERGROUP))

    assert not is_allowed_group(private, messenger)
    assert is_allowed_group(group, messenger)


@pytest.mark.asyncio
async def test_debug_error_never_echoes_exception_or_secret() -> None:
    sent: list[str] = []

    class FakeBot:
        async def send_message(self, **kwargs):
            sent.append(kwargs["text"])

    messenger = TopicMessenger(FakeBot(), {-1001: TopicPolicy(debug=1, posts=2, schedule=3)})
    await messenger.safe_debug_error(-1001, "VK API")

    assert sent == ["⚠️ Сбой задачи: VK API. Повторите позже."]


def test_help_lists_all_available_command_families() -> None:
    assert "!all" in HELP_TEXT
    assert "!vk add" in HELP_TEXT
    assert "!vk list" in HELP_TEXT
    assert "!vk remove" in HELP_TEXT
    assert "!schedule mon|tue|wed|thu|fri|sat" in HELP_TEXT


def test_schedule_text_is_split_without_losing_content() -> None:
    text = "один\nдва\nтри"

    assert split_plaintext(text, max_chars=8) == ["один\nдва", "три"]


def test_schedule_markdown_escapes_code_delimiters_and_splits_valid_blocks() -> None:
    chunks = format_schedule_markdown("первая\\строка\n`вторая`\nтретья", max_chars=22)

    assert len(chunks) > 1
    assert all(chunk.startswith("```\n") and chunk.endswith("\n```") and len(chunk) <= 22 for chunk in chunks)
    assert "\\\\" in "".join(chunks)
    assert "\\`" in "".join(chunks)


@pytest.mark.asyncio
async def test_schedule_is_sent_as_markdown_v2_code_block() -> None:
    calls: list[dict[str, object]] = []

    class FakeBot:
        async def send_message(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return SimpleNamespace(message_id=1)

    messenger = TopicMessenger(FakeBot(), {-1001: TopicPolicy(debug=1, posts=2, schedule=3)})

    await messenger.send_schedule(-1001, "08:30–10:05\nМатематика")

    assert calls == [
        {
            "chat_id": -1001,
            "message_thread_id": 3,
            "text": "```\n08:30–10:05\nМатематика\n```",
            "parse_mode": ParseMode.MARKDOWN_V2,
        }
    ]


@pytest.mark.asyncio
async def test_help_is_sent_as_html_only_for_static_help_text() -> None:
    sent: dict[str, object] = {}

    class FakeMessenger:
        async def send_debug(self, chat_id: int, text: str, **kwargs: object) -> None:
            sent.update(chat_id=chat_id, text=text, **kwargs)

    await send_help(-1001, FakeMessenger())  # type: ignore[arg-type]

    assert sent == {"chat_id": -1001, "text": HELP_TEXT, "parse_mode": "HTML"}
