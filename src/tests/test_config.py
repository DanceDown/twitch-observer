from __future__ import annotations

from src.config import AppConfig


def test_app_config_uses_default_channel_cache_refresh_interval(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_CHANNEL_CACHE_API_REFRESH_SECONDS", raising=False)
    config = AppConfig()
    assert config.twitch_channel_cache_api_refresh_seconds == 43200
