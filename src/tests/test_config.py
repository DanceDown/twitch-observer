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


def test_app_config_uses_default_message_write_spool_path(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_MESSAGE_WRITE_SPOOL_PATH", raising=False)
    config = AppConfig()
    assert config.twitch_message_write_spool_path == ".data/message-write-spool.json"


def test_app_config_allows_disabling_message_write_spool(monkeypatch) -> None:
    monkeypatch.setenv("TWITCH_MESSAGE_WRITE_SPOOL_PATH", "")
    config = AppConfig()
    assert config.twitch_message_write_spool_path is None


def test_app_config_uses_default_discord_delivery_max_attempts(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_DELIVERY_MAX_ATTEMPTS", raising=False)
    config = AppConfig()
    assert config.discord_delivery_max_attempts == 3


def test_app_config_reads_discord_delivery_max_attempts(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_DELIVERY_MAX_ATTEMPTS", "5")
    config = AppConfig()
    assert config.discord_delivery_max_attempts == 5


def test_app_config_uses_default_irc_reconnect_delays(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_IRC_RECONNECT_INITIAL_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("TWITCH_IRC_RECONNECT_MAX_DELAY_SECONDS", raising=False)
    config = AppConfig()
    assert config.twitch_irc_reconnect_initial_delay_seconds == 1
    assert config.twitch_irc_reconnect_max_delay_seconds == 60


def test_app_config_uses_default_chat_processing_queue_settings(monkeypatch) -> None:
    monkeypatch.delenv("TWITCH_CHAT_PROCESSING_QUEUE_SIZE", raising=False)
    monkeypatch.delenv("TWITCH_CHAT_PROCESSING_WORKERS", raising=False)
    monkeypatch.delenv("TWITCH_CHAT_PROCESSING_STOP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("TWITCH_CHAT_METADATA_LOOKUP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("TWITCH_USER_CACHE_MEMORY_SIZE", raising=False)
    monkeypatch.delenv("DISCORD_TRACKING_DELIVERY_STOP_TIMEOUT_SECONDS", raising=False)
    config = AppConfig()
    assert config.twitch_chat_processing_queue_size == 10000
    assert config.twitch_chat_processing_workers == 4
    assert config.twitch_chat_processing_stop_timeout_seconds == 30
    assert config.twitch_chat_metadata_lookup_timeout_seconds == 5
    assert config.twitch_user_cache_memory_size == 20000
    assert config.discord_tracking_delivery_stop_timeout_seconds == 30


def test_app_config_reads_chat_processing_queue_settings(monkeypatch) -> None:
    monkeypatch.setenv("TWITCH_CHAT_PROCESSING_QUEUE_SIZE", "200")
    monkeypatch.setenv("TWITCH_CHAT_PROCESSING_WORKERS", "8")
    monkeypatch.setenv("TWITCH_CHAT_PROCESSING_STOP_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("TWITCH_CHAT_METADATA_LOOKUP_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("TWITCH_USER_CACHE_MEMORY_SIZE", "50000")
    monkeypatch.setenv("DISCORD_TRACKING_DELIVERY_STOP_TIMEOUT_SECONDS", "12.5")
    config = AppConfig()
    assert config.twitch_chat_processing_queue_size == 200
    assert config.twitch_chat_processing_workers == 8
    assert config.twitch_chat_processing_stop_timeout_seconds == 7.5
    assert config.twitch_chat_metadata_lookup_timeout_seconds == 2.5
    assert config.twitch_user_cache_memory_size == 50000
    assert config.discord_tracking_delivery_stop_timeout_seconds == 12.5
