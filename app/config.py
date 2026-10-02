"""Typed, secret-safe runtime configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True, slots=True)
class TopicPolicy:
    """The only forum targets where the bot may send messages for one chat."""

    debug: int | None
    posts: int | None
    schedule: int | None

    def allows_vk_target(self, thread_id: int | None) -> bool:
        return thread_id is not None and thread_id in {self.posts, self.schedule}


class Settings(BaseSettings):
    """Environment settings. Never call ``model_dump`` with secrets in logs."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: SecretStr
    vk_api_token: SecretStr
    database_url: str
    allowed_chat_ids: str = ""
    topic_policy_json: str = "{}"
    member_ids_json: str = "[]"
    vk_api_version: str = "5.199"
    vk_poll_interval_seconds: int = Field(default=60, ge=15, le=3600)
    http_host: str = "0.0.0.0"
    http_port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = "INFO"
    go_schedule_binary: str = "schedule-bot"

    @field_validator("allowed_chat_ids")
    @classmethod
    def validate_chat_ids(cls, value: str) -> str:
        for item in filter(None, (part.strip() for part in value.split(","))):
            int(item)
        return value

    @property
    def allowed_chats(self) -> frozenset[int]:
        return frozenset(int(part.strip()) for part in self.allowed_chat_ids.split(",") if part.strip())

    @property
    def topic_policies(self) -> dict[int, TopicPolicy]:
        raw: Any = json.loads(self.topic_policy_json)
        if not isinstance(raw, dict):
            raise ValueError("TOPIC_POLICY_JSON must be an object keyed by chat ID")
        policies: dict[int, TopicPolicy] = {}
        for chat_id_text, values in raw.items():
            if not isinstance(values, dict):
                raise ValueError("topic policy values must be objects")
            policies[int(chat_id_text)] = TopicPolicy(
                debug=_optional_int(values.get("debug")),
                posts=_optional_int(values.get("posts")),
                schedule=_optional_int(values.get("schedule")),
            )
        unknown = set(policies) - self.allowed_chats
        if unknown:
            raise ValueError("topic policy contains chat IDs outside ALLOWED_CHAT_IDS")
        return policies

    @property
    def member_ids(self) -> tuple[int, ...]:
        raw: Any = json.loads(self.member_ids_json)
        if not isinstance(raw, list) or any(not isinstance(item, int) for item in raw):
            raise ValueError("MEMBER_IDS_JSON must be a JSON array of integer Telegram user IDs")
        return tuple(dict.fromkeys(raw))


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("topic IDs must be integers or null")
    return int(value)
