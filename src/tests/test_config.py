from __future__ import annotations

from src.config import AppConfig


def test_app_config_uses_default_channel_cache_refresh_interval(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_CHANNEL_CACHE_API_REFRESH_SECONDS", raising=False)
    config = AppConfig()
    assert config.twitch_channel_cache_api_refresh_seconds == 43200


def test_app_config_uses_default_metadata_refresh_request_spacing(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_METADATA_REFRESH_REQUEST_SPACING_SECONDS", raising=False)
    config = AppConfig()
    assert config.twitch_metadata_refresh_request_spacing_seconds == 0


def test_app_config_uses_default_metadata_refresh_batch_size(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_METADATA_REFRESH_BATCH_SIZE", raising=False)
    config = AppConfig()
    assert config.twitch_metadata_refresh_batch_size == 100


def test_app_config_uses_default_message_write_batch_size(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_MESSAGE_WRITE_BATCH_SIZE", raising=False)
    config = AppConfig()
    assert config.twitch_message_write_batch_size == 50


def test_app_config_uses_default_message_write_flush_interval(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_MESSAGE_WRITE_FLUSH_INTERVAL_SECONDS", raising=False)
    config = AppConfig()
    assert config.twitch_message_write_flush_interval_seconds == 0.25
