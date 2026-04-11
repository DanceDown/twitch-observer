from __future__ import annotations

"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field


def _split_csv(value: str) -> list[str]:
    """Split a comma-separated environment variable into normalized values."""
    return [item.strip().lower() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class AppConfig:
    """Central runtime configuration for adapters, database and services."""

    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_application_id: int | None = field(
        default_factory=lambda: int(value) if (value := os.getenv("DISCORD_APPLICATION_ID", "").strip()) else None
    )
    postgres_db: str = field(default_factory=lambda: os.getenv("POSTGRES_DB", "twitch_observer"))
    postgres_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "twitch_observer"))
    postgres_password: str = field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", "change-me"))
    postgres_host: str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    postgres_port: int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    twitch_api_base_url: str = field(default_factory=lambda: os.getenv("TWITCH_API_BASE_URL", "https://api.twitch.tv/helix"))
    twitch_auth_base_url: str = field(
        default_factory=lambda: os.getenv("TWITCH_AUTH_BASE_URL", "https://id.twitch.tv/oauth2")
    )
    twitch_client_id: str = field(default_factory=lambda: os.getenv("TWITCH_CLIENT_ID", ""))
    twitch_client_secret: str = field(default_factory=lambda: os.getenv("TWITCH_CLIENT_SECRET", ""))
    twitch_irc_host: str = field(default_factory=lambda: os.getenv("TWITCH_IRC_HOST", "irc.chat.twitch.tv"))
    twitch_irc_port: int = field(default_factory=lambda: int(os.getenv("TWITCH_IRC_PORT", "6697")))
    twitch_irc_use_ssl: bool = field(
        default_factory=lambda: os.getenv("TWITCH_IRC_USE_SSL", "true").lower() in {"1", "true", "yes", "on"}
    )
    twitch_irc_channels: list[str] = field(
        default_factory=lambda: _split_csv(os.getenv("TWITCH_IRC_CHANNELS", ""))
    )
    twitch_irc_nick_prefix: str = field(default_factory=lambda: os.getenv("TWITCH_IRC_NICK_PREFIX", "justinfan"))
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
