from __future__ import annotations

from src.config import AppConfig


def test_app_config_uses_default_metadata_refresh_interval(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_METADATA_REFRESH_INTERVAL_SECONDS", raising=False)
    config = AppConfig()
    assert config.twitch_metadata_refresh_interval_seconds == 43200


def test_app_config_uses_default_presence_watchdog_interval(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_PRESENCE_WATCHDOG_INTERVAL_SECONDS", raising=False)
    config = AppConfig()
    assert config.discord_presence_watchdog_interval_seconds == 60


def test_app_config_uses_default_presence_stale_after(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_PRESENCE_STALE_AFTER_SECONDS", raising=False)
    config = AppConfig()
    assert config.discord_presence_stale_after_seconds == 180


def test_app_config_uses_default_presence_update_timeout(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_PRESENCE_UPDATE_TIMEOUT_SECONDS", raising=False)
    config = AppConfig()
    assert config.discord_presence_update_timeout_seconds == 15


def test_app_config_reads_presence_update_timeout(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_PRESENCE_UPDATE_TIMEOUT_SECONDS", "7.5")
    config = AppConfig()
    assert config.discord_presence_update_timeout_seconds == 7.5


def test_app_config_uses_default_pattern_compile_cache_size(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_PATTERN_COMPILE_CACHE_SIZE", raising=False)
    config = AppConfig()
    assert config.twitch_pattern_compile_cache_size == 512


def test_app_config_reads_pattern_compile_cache_size(monkeypatch) -> None:
    monkeypatch.setenv("TWITCH_PATTERN_COMPILE_CACHE_SIZE", "1024")
    config = AppConfig()
    assert config.twitch_pattern_compile_cache_size == 1024


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


def test_app_config_uses_default_discord_delivery_max_attempts(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_DELIVERY_MAX_ATTEMPTS", raising=False)
    config = AppConfig()
    assert config.discord_delivery_max_attempts == 10


def test_app_config_reads_discord_delivery_max_attempts(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_DELIVERY_MAX_ATTEMPTS", "5")
    config = AppConfig()
    assert config.discord_delivery_max_attempts == 5
