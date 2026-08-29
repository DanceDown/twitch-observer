"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_csv(value: str) -> list[str]:
    """Split a comma-separated environment variable into normalized values."""
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _get_int(name: str, default: str) -> int:
    """Read one integer environment variable with a centralized fallback."""
    return int(os.getenv(name, default))


def _get_float(name: str, default: str) -> float:
    """Read one float environment variable with a centralized fallback."""
    return float(os.getenv(name, default))


def _get_bool(name: str, default: str) -> bool:
    """Read one boolean environment variable with a centralized fallback."""
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def get_discord_delivery_max_attempts() -> int:
    """Read the configured Discord delivery retry limit with one safe minimum."""
    return max(1, _get_int("DISCORD_DELIVERY_MAX_ATTEMPTS", "3"))


@dataclass(slots=True)
class AppConfig:
    """Central runtime configuration for entrypoints, gateways, database and services."""

    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_application_id: int | None = field(
        default_factory=lambda: int(value) if (value := os.getenv("DISCORD_APPLICATION_ID", "").strip()) else None
    )
    postgres_db: str = field(default_factory=lambda: os.getenv("POSTGRES_DB", "twitch_observer"))
    postgres_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "twitch_observer"))
    postgres_password: str = field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", "change-me"))
    postgres_host: str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    postgres_port: int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    postgres_pool_size: int = field(default_factory=lambda: _get_int("POSTGRES_POOL_SIZE", "8"))
    postgres_pool_acquire_timeout_seconds: float = field(default_factory=lambda: _get_float("POSTGRES_POOL_ACQUIRE_TIMEOUT_SECONDS", "5"))
    twitch_api_base_url: str = field(default_factory=lambda: os.getenv("TWITCH_API_BASE_URL", "https://api.twitch.tv/helix"))
    twitch_auth_base_url: str = field(default_factory=lambda: os.getenv("TWITCH_AUTH_BASE_URL", "https://id.twitch.tv/oauth2"))
    twitch_client_id: str = field(default_factory=lambda: os.getenv("TWITCH_CLIENT_ID", ""))
    twitch_client_secret: str = field(default_factory=lambda: os.getenv("TWITCH_CLIENT_SECRET", ""))
    twitch_irc_host: str = field(default_factory=lambda: os.getenv("TWITCH_IRC_HOST", "irc.chat.twitch.tv"))
    twitch_irc_port: int = field(default_factory=lambda: int(os.getenv("TWITCH_IRC_PORT", "6697")))
    twitch_irc_use_ssl: bool = field(default_factory=lambda: os.getenv("TWITCH_IRC_USE_SSL", "true").lower() in {"1", "true", "yes", "on"})
    twitch_irc_channels: list[str] = field(default_factory=lambda: _split_csv(os.getenv("TWITCH_IRC_CHANNELS", "")))
    twitch_irc_nick_prefix: str = field(default_factory=lambda: os.getenv("TWITCH_IRC_NICK_PREFIX", "justinfan"))
    twitch_irc_connection_check_interval_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_IRC_CONNECTION_CHECK_INTERVAL_SECONDS", "10")
    )
    twitch_irc_reconnect_initial_delay_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_IRC_RECONNECT_INITIAL_DELAY_SECONDS", "1")
    )
    twitch_irc_reconnect_max_delay_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_IRC_RECONNECT_MAX_DELAY_SECONDS", "60")
    )
    twitch_chat_processing_queue_size: int = field(default_factory=lambda: _get_int("TWITCH_CHAT_PROCESSING_QUEUE_SIZE", "10000"))
    twitch_chat_processing_workers: int = field(default_factory=lambda: _get_int("TWITCH_CHAT_PROCESSING_WORKERS", "4"))
    twitch_chat_processing_stop_timeout_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_CHAT_PROCESSING_STOP_TIMEOUT_SECONDS", "30")
    )
    twitch_chat_metadata_lookup_timeout_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_CHAT_METADATA_LOOKUP_TIMEOUT_SECONDS", "5")
    )
    twitch_user_cache_memory_size: int = field(default_factory=lambda: _get_int("TWITCH_USER_CACHE_MEMORY_SIZE", "20000"))
    twitch_pattern_compile_cache_size: int = field(default_factory=lambda: _get_int("TWITCH_PATTERN_COMPILE_CACHE_SIZE", "512"))
    twitch_metadata_refresh_interval_seconds: int = field(
        default_factory=lambda: _get_int("TWITCH_METADATA_REFRESH_INTERVAL_SECONDS", "43200")
    )
    twitch_metadata_refresh_request_spacing_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_METADATA_REFRESH_REQUEST_SPACING_SECONDS", "0")
    )
    twitch_metadata_refresh_batch_size: int = field(default_factory=lambda: _get_int("TWITCH_METADATA_REFRESH_BATCH_SIZE", "100"))
    twitch_live_monitor_poll_interval_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_LIVE_MONITOR_POLL_INTERVAL_SECONDS", "30")
    )
    twitch_live_monitor_batch_size: int = field(default_factory=lambda: _get_int("TWITCH_LIVE_MONITOR_BATCH_SIZE", "100"))
    twitch_live_monitor_refresh_on_startup: bool = field(
        default_factory=lambda: _get_bool("TWITCH_LIVE_MONITOR_REFRESH_ON_STARTUP", "true")
    )
    twitch_account_token_refresh_skew_seconds: int = field(
        default_factory=lambda: _get_int("TWITCH_ACCOUNT_TOKEN_REFRESH_SKEW_SECONDS", "30")
    )
    twitch_app_access_token_refresh_skew_seconds: int = field(
        default_factory=lambda: _get_int("TWITCH_APP_ACCESS_TOKEN_REFRESH_SKEW_SECONDS", "60")
    )
    twitch_device_flow_poll_interval_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_DEVICE_FLOW_POLL_INTERVAL_SECONDS", "2")
    )
    twitch_device_flow_slowdown_step_seconds: int = field(default_factory=lambda: _get_int("TWITCH_DEVICE_FLOW_SLOWDOWN_STEP_SECONDS", "5"))
    discord_presence_poll_interval_seconds: float = field(
        default_factory=lambda: _get_float("DISCORD_PRESENCE_POLL_INTERVAL_SECONDS", "60")
    )
    discord_presence_watchdog_interval_seconds: float = field(
        default_factory=lambda: _get_float("DISCORD_PRESENCE_WATCHDOG_INTERVAL_SECONDS", "60")
    )
    discord_presence_stale_after_seconds: float = field(default_factory=lambda: _get_float("DISCORD_PRESENCE_STALE_AFTER_SECONDS", "180"))
    discord_presence_update_timeout_seconds: float = field(
        default_factory=lambda: _get_float("DISCORD_PRESENCE_UPDATE_TIMEOUT_SECONDS", "15")
    )
    discord_presence_lookback_minutes: int = field(default_factory=lambda: _get_int("DISCORD_PRESENCE_LOOKBACK_MINUTES", "5"))
    discord_presence_message_limit: int = field(default_factory=lambda: _get_int("DISCORD_PRESENCE_MESSAGE_LIMIT", "50"))
    discord_presence_max_status_length: int = field(default_factory=lambda: _get_int("DISCORD_PRESENCE_MAX_STATUS_LENGTH", "120"))
    discord_delivery_max_attempts: int = field(default_factory=get_discord_delivery_max_attempts)
    discord_tracking_delivery_stop_timeout_seconds: float = field(
        default_factory=lambda: _get_float("DISCORD_TRACKING_DELIVERY_STOP_TIMEOUT_SECONDS", "30")
    )
    twitch_message_write_batch_size: int = field(default_factory=lambda: _get_int("TWITCH_MESSAGE_WRITE_BATCH_SIZE", "50"))
    twitch_message_write_flush_interval_seconds: float = field(
        default_factory=lambda: _get_float("TWITCH_MESSAGE_WRITE_FLUSH_INTERVAL_SECONDS", "0.25")
    )
    twitch_message_write_spool_path: str | None = field(
        default_factory=lambda: os.getenv("TWITCH_MESSAGE_WRITE_SPOOL_PATH", ".data/message-write-spool.json").strip() or None
    )
    discord_write_reply_candidate_max_age_minutes: int = field(
        default_factory=lambda: _get_int("DISCORD_WRITE_REPLY_CANDIDATE_MAX_AGE_MINUTES", "1440")
    )
    discord_write_reply_candidate_limit: int = field(default_factory=lambda: _get_int("DISCORD_WRITE_REPLY_CANDIDATE_LIMIT", "25"))
    irc_bootstrap_connect_timeout_seconds: float = field(default_factory=lambda: _get_float("IRC_BOOTSTRAP_CONNECT_TIMEOUT_SECONDS", "15"))
    irc_channel_resync_interval_seconds: float = field(default_factory=lambda: _get_float("IRC_CHANNEL_RESYNC_INTERVAL_SECONDS", "300"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    @property
    def postgres_dsn(self) -> str:
        """Build a psycopg-compatible DSN string."""
        return (
            f"dbname={self.postgres_db} "
            f"user={self.postgres_user} "
            f"password={self.postgres_password} "
            f"host={self.postgres_host} "
            f"port={self.postgres_port}"
        )
