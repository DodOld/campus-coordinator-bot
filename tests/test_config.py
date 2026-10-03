from app.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "telegram_bot_token": "telegram-token",
        "vk_api_token": "vk-token",
        "database_url": "postgresql+asyncpg://bot:password@db:5432/bot",
    }
    values.update(overrides)
    return Settings(**values)


def test_telegram_proxy_url_is_optional() -> None:
    assert _settings().telegram_proxy_url is None


def test_telegram_proxy_url_is_kept_secret() -> None:
    settings = _settings(telegram_proxy_url="socks5://user:password@proxy.example:1080")

    assert settings.telegram_proxy_url is not None
    assert settings.telegram_proxy_url.get_secret_value().startswith("socks5://")
    assert "password" not in repr(settings.telegram_proxy_url)
