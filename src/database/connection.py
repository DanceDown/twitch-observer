from __future__ import annotations

"""Database access layer for PostgreSQL-backed persistence."""

from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from src.config import AppConfig
from src.events.event_types import TwitchChatMessageEvent


@dataclass(slots=True, frozen=True)
class ThreadRecord:
    """Persisted Discord channel configuration root."""

    thread_id: int
    owner_id: int
    discord_channel_id: int
    enabled: bool
    color: str | None
    account_id: int | None = None


@dataclass(slots=True, frozen=True)
class TwitchAccountRecord:
    """Persisted Twitch user token linked to one Discord user."""

    account_id: int
    discord_user_id: int
    twitch_user_id: str
    twitch_login: str
    client_id: str
    access_token: str | None
    refresh_token: str | None
    expires_at: str | None
    scope: tuple[str, ...]
    token_type: str | None


@dataclass(slots=True, frozen=True)
class TwitchDeviceFlowRecord:
    """Persisted pending Twitch Device Code login for one Discord user."""

    discord_user_id: int
    discord_channel_id: int | None
    device_code: str
    user_code: str
    verification_uri: str
    interval_seconds: int
    expires_at: str
    scope: tuple[str, ...]
    status: str
    last_error: str | None
    last_polled_at: str | None


@dataclass(slots=True, frozen=True)
class TwitchUserCacheRecord:
    """Persisted Twitch user metadata used to avoid repeated Helix lookups."""

    twitch_user_id: str
    twitch_login: str
    display_name: str
    profile_image_url: str | None
    updated_at: str
    last_api_refresh_at: str | None


@dataclass(slots=True, frozen=True)
class ChannelRecord:
    """Persisted Twitch channel subscription for one thread."""

    thread_id: int
    twitch_channel_id: str
    color: str | None
    is_live: bool | None = None
    last_live_status_at: str | None = None


@dataclass(slots=True, frozen=True)
class TrackedUserRecord:
    """Persisted tracked Twitch user for one thread."""

    thread_id: int
    twitch_user_id: str


@dataclass(slots=True, frozen=True)
class PatternRecord:
    """Persisted match rule for one thread."""

    thread_id: int
    p_index: int
    regex: str
    channel_scope_mode: str
    channel_scope_ids: tuple[str, ...]
    user_scope_mode: str
    user_scope_ids: tuple[str, ...]
    sub_state: str
    offline_state: str
    is_regex: bool
    case_sensitive: bool
    color: str | None
    disabled: bool
    notify: bool
    priority: int
    reply_message: str | None = None
    reply_as_reply: bool = False


@dataclass(slots=True, frozen=True)
class ReplyRecord:
    """Persisted auto-reply attached to one pattern."""

    thread_id: int
    p_index: int
    reply_message: str
    reply_as_reply: bool
    disabled: bool


@dataclass(slots=True, frozen=True)
class ChannelEventReplyRecord:
    """Persisted auto-reply triggered by a tracked channel going live or offline."""

    thread_id: int
    twitch_channel_id: str
    event_state: str
    reply_message: str
    disabled: bool


@dataclass(slots=True, frozen=True)
class UserPermissionRecord:
    """Persisted additional permission grants for one Discord user in one thread."""

    discord_user_id: int
    thread_id: int
    permissions: int


@dataclass(slots=True, frozen=True)
class RecentMessageRecord:
    """Compact stored Twitch message used for status text and lightweight displays."""

    username: str
    content: str
    timestamp: datetime


class MessageRepository:
    """Persistence interface for normalized Twitch chat messages."""

    def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def list_recent_messages(self, *, since: datetime, limit: int) -> list[RecentMessageRecord]:  # pragma: no cover - interface
        raise NotImplementedError


class ThreadRepository:
    """Persistence interface for Discord thread/channel configuration roots."""

    def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:  # pragma: no cover
        raise NotImplementedError

    def delete_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_enabled(self, *, discord_channel_id: int, enabled: bool) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_color(self, *, discord_channel_id: int, color: str | None) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_account_id(self, *, discord_channel_id: int, account_id: int | None) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:  # pragma: no cover
        raise NotImplementedError


class TwitchAccountRepository:
    """Persistence interface for linked Twitch accounts."""

    def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:  # pragma: no cover
        raise NotImplementedError

    def create_account(
        self,
        *,
        discord_user_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord:  # pragma: no cover
        raise NotImplementedError

    def update_account(
        self,
        *,
        account_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord | None:  # pragma: no cover
        raise NotImplementedError

    def remove_by_account_id(self, account_id: int) -> bool:  # pragma: no cover
        raise NotImplementedError

    def get_by_discord_user_id(self, discord_user_id: int) -> TwitchAccountRecord | None:  # pragma: no cover - compatibility
        raise NotImplementedError

    def upsert_account(
        self,
        *,
        discord_user_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord:  # pragma: no cover - compatibility
        raise NotImplementedError

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:  # pragma: no cover - compatibility
        raise NotImplementedError


class TwitchDeviceFlowRepository:
    """Persistence interface for pending Twitch Device Code logins."""

    def get_by_discord_channel_id(self, discord_channel_id: int) -> TwitchDeviceFlowRecord | None:  # pragma: no cover
        raise NotImplementedError

    def upsert_pending_flow(
        self,
        *,
        discord_user_id: int,
        discord_channel_id: int,
        device_code: str,
        user_code: str,
        verification_uri: str,
        interval_seconds: int,
        expires_at: str,
        scope: tuple[str, ...],
    ) -> TwitchDeviceFlowRecord:  # pragma: no cover
        raise NotImplementedError

    def list_pending_flows(self) -> list[TwitchDeviceFlowRecord]:  # pragma: no cover
        raise NotImplementedError

    def mark_failed(self, *, discord_channel_id: int, last_error: str) -> TwitchDeviceFlowRecord | None:  # pragma: no cover
        raise NotImplementedError

    def touch_polled(self, *, discord_channel_id: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def update_interval(self, *, discord_channel_id: int, interval_seconds: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def remove_by_discord_channel_id(self, discord_channel_id: int) -> bool:  # pragma: no cover
        raise NotImplementedError

    def get_by_discord_user_id(self, discord_user_id: int) -> TwitchDeviceFlowRecord | None:  # pragma: no cover - compatibility
        raise NotImplementedError

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:  # pragma: no cover - compatibility
        raise NotImplementedError


class TwitchUserCacheRepository:
    """Persistence interface for Twitch user metadata cached by ID and login."""

    def get_by_user_id(self, twitch_user_id: str) -> TwitchUserCacheRecord | None:  # pragma: no cover
        raise NotImplementedError

    def get_by_login(self, twitch_login: str) -> TwitchUserCacheRecord | None:  # pragma: no cover
        raise NotImplementedError

    def upsert_from_api(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str,
        profile_image_url: str | None,
    ) -> TwitchUserCacheRecord:  # pragma: no cover
        raise NotImplementedError

    def observe_from_chat(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str | None,
    ) -> TwitchUserCacheRecord:  # pragma: no cover
        raise NotImplementedError


class ChannelRepository:
    """Persistence interface for per-thread Twitch channel subscriptions."""

    def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:  # pragma: no cover
        raise NotImplementedError

    def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_live_state_for_twitch_channel(
        self,
        *,
        twitch_channel_id: str,
        is_live: bool,
        changed_at: str | None,
    ) -> int:  # pragma: no cover
        raise NotImplementedError

    def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:  # pragma: no cover
        raise NotImplementedError

    def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:  # pragma: no cover
        raise NotImplementedError

    def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_all_twitch_channel_ids(self) -> list[str]:  # pragma: no cover
        raise NotImplementedError


class TrackedUserRepository:
    """Persistence interface for per-thread tracked Twitch users."""

    def get_by_thread_and_twitch_user(self, thread_id: int, twitch_user_id: str) -> TrackedUserRecord | None:  # pragma: no cover
        raise NotImplementedError

    def add_user(self, thread_id: int, twitch_user_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def remove_user(self, thread_id: int, twitch_user_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_users_for_thread(self, thread_id: int) -> list[TrackedUserRecord]:  # pragma: no cover
        raise NotImplementedError

    def count_pattern_scope_references(self, *, thread_id: int, twitch_user_id: str) -> int:  # pragma: no cover
        raise NotImplementedError


class PatternRepository:
    """Persistence interface for per-thread ping/regex definitions."""

    def find_exact_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
    ) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def add_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        disabled: bool,
        priority: int,
    ) -> PatternRecord:  # pragma: no cover
        raise NotImplementedError

    def remove_pattern(self, *, thread_id: int, p_index: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_pattern_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_pattern_priority(self, *, thread_id: int, p_index: int, priority: int) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def update_pattern(
        self,
        *,
        thread_id: int,
        p_index: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        priority: int,
    ) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:  # pragma: no cover
        raise NotImplementedError

    def get_pattern_by_id(
        self,
        *,
        thread_id: int,
        p_index: int,
    ) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_patterns_for_thread(
        self,
        thread_id: int,
        *,
        is_regex: bool | None = None,
    ) -> list[PatternRecord]:  # pragma: no cover
        raise NotImplementedError

    def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:  # pragma: no cover
        raise NotImplementedError


class ReplyRepository:
    """Persistence interface for auto-replies attached to patterns."""

    def get_by_pattern(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def add_reply(
        self,
        *,
        thread_id: int,
        p_index: int,
        reply_message: str,
        reply_as_reply: bool,
    ) -> ReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def remove_reply(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_reply_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> ReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ReplyRecord]:  # pragma: no cover
        raise NotImplementedError

    def disable_replies_for_thread(self, thread_id: int) -> int:  # pragma: no cover
        raise NotImplementedError

    def enable_replies_for_thread(self, thread_id: int) -> int:  # pragma: no cover
        raise NotImplementedError


class ChannelEventReplyRepository:
    """Persistence interface for live/offline-triggered auto-replies."""

    def get_by_channel_event(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
    ) -> ChannelEventReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def upsert_reply(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
        reply_message: str,
    ) -> ChannelEventReplyRecord:  # pragma: no cover
        raise NotImplementedError

    def remove_reply(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
    ) -> ChannelEventReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_reply_disabled(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
        disabled: bool,
    ) -> ChannelEventReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_replies_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[ChannelEventReplyRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_replies_for_channel_event(
        self,
        *,
        twitch_channel_id: str,
        event_state: str,
        include_disabled: bool = False,
    ) -> list[ChannelEventReplyRecord]:  # pragma: no cover
        raise NotImplementedError


class UserPermissionRepository:
    """Persistence interface for additional per-thread Discord permissions."""

    def get_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> UserPermissionRecord | None:  # pragma: no cover
        raise NotImplementedError

    def upsert_permissions(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
        permissions: int,
    ) -> UserPermissionRecord:  # pragma: no cover
        raise NotImplementedError

    def remove_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> bool:  # pragma: no cover
        raise NotImplementedError

    def list_for_thread(self, *, thread_id: int) -> list[UserPermissionRecord]:  # pragma: no cover
        raise NotImplementedError


@dataclass(slots=True)
class PostgresDatabase:
    """Thin wrapper around a psycopg connection."""

    config: AppConfig
    connection: psycopg.Connection | None = None

    def connect(self) -> None:
        """Open the PostgreSQL connection lazily."""
        if self.connection is None or self.connection.closed:
            self.connection = psycopg.connect(self.config.postgres_dsn, autocommit=True)

    def close(self) -> None:
        """Close the PostgreSQL connection if it is open."""
        if self.connection is not None and not self.connection.closed:
            self.connection.close()

    def healthcheck(self) -> None:
        """Validate that PostgreSQL is reachable."""
        self.connect()
        assert self.connection is not None
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

    def ensure_schema_compatibility(self) -> None:
        """Apply lightweight compatibility migrations for existing local databases."""
        self.connect()
        assert self.connection is not None
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE thread
                ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
            cursor.execute(
                """
                ALTER TABLE thread
                ALTER COLUMN color DROP NOT NULL
                """
            )
            cursor.execute(
                """
                ALTER TABLE thread
                ALTER COLUMN color DROP DEFAULT
                """
            )
            cursor.execute(
                """
                ALTER TABLE thread
                DROP COLUMN IF EXISTS use_twitch_colors
                """
            )
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_type t
                        JOIN pg_enum e ON e.enumtypid = t.oid
                        WHERE t.typname = 'user_scope_mode_enum' AND e.enumlabel = 'all_tracked'
                    ) THEN
                        ALTER TYPE USER_SCOPE_MODE_ENUM ADD VALUE 'all_tracked';
                    END IF;
                END $$;
                """
            )
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_type t
                        JOIN pg_enum e ON e.enumtypid = t.oid
                        WHERE t.typname = 'user_scope_mode_enum' AND e.enumlabel = 'all_tracked_except_selected'
                    ) THEN
                        ALTER TYPE USER_SCOPE_MODE_ENUM ADD VALUE 'all_tracked_except_selected';
                    END IF;
                END $$;
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_user (
                    thread_id INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
                    twitch_user_id TEXT NOT NULL,
                    PRIMARY KEY (thread_id, twitch_user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tracked_user_twitch_user_id
                ON tracked_user(twitch_user_id)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS twitch_user_cache (
                    twitch_user_id TEXT PRIMARY KEY,
                    twitch_login TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    profile_image_url TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_api_refresh_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_twitch_user_cache_login
                ON twitch_user_cache(twitch_login)
                """
            )
            cursor.execute(
                """
                ALTER TABLE channel
                ADD COLUMN IF NOT EXISTS is_live BOOLEAN
                """
            )
            cursor.execute(
                """
                ALTER TABLE channel
                ADD COLUMN IF NOT EXISTS last_live_status_at TIMESTAMPTZ
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS channel_event_reply (
                    thread_id INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
                    twitch_channel_id TEXT NOT NULL,
                    event_state OFFLINE_STATE_ENUM NOT NULL,
                    reply_message TEXT NOT NULL,
                    disabled BOOLEAN NOT NULL DEFAULT FALSE,
                    PRIMARY KEY (thread_id, twitch_channel_id, event_state),
                    CONSTRAINT fk_channel_event_reply_channel
                        FOREIGN KEY (thread_id, twitch_channel_id)
                        REFERENCES channel(thread_id, twitch_channel_id)
                        ON DELETE CASCADE,
                    CONSTRAINT chk_channel_event_reply_state
                        CHECK (event_state IN ('offline', 'online'))
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_channel_event_reply_lookup
                ON channel_event_reply(twitch_channel_id, event_state, disabled)
                """
            )


@dataclass(slots=True)
class PostgresMessageRepository(MessageRepository):
    """Store normalized Twitch chat messages in PostgreSQL."""

    database: PostgresDatabase

    def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        """Persist one incoming Twitch message if it has not been stored yet."""
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO message (
                    message_id,
                    twitch_channel_id,
                    timestamp,
                    twitch_user_id,
                    username,
                    content,
                    is_reply_to,
                    is_bot
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (
                    event.message_id or self._build_fallback_message_id(event),
                    event.broadcaster_id or event.channel_login,
                    event.sent_at,
                    event.author_id or event.author_login,
                    event.author_display_name or event.author_login,
                    event.content,
                    event.reply_parent_message_id,
                ),
            )

    def list_recent_messages(self, *, since: datetime, limit: int) -> list[RecentMessageRecord]:
        """Load recent Twitch messages for presence updates or lightweight recency-based features."""
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT username, content, timestamp
                FROM message
                WHERE timestamp >= %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (since, limit),
            )
            rows = cursor.fetchall()
        return [
            RecentMessageRecord(
                username=str(row[0]),
                content=str(row[1]),
                timestamp=row[2],
            )
            for row in rows
        ]

    @staticmethod
    def _build_fallback_message_id(event: TwitchChatMessageEvent) -> str:
        """Build a deterministic fallback ID when Twitch did not provide one."""
        timestamp = event.sent_at.isoformat()
        return f"{event.channel_login}:{event.author_login}:{timestamp}:{hash(event.content)}"


@dataclass(slots=True)
class PostgresThreadRepository(ThreadRepository):
    """Store and retrieve thread roots in PostgreSQL."""

    database: PostgresDatabase

    def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, owner_id, discord_channel_id, enabled, color, account_id
                FROM thread
                WHERE discord_channel_id = %s
                """,
                (discord_channel_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            enabled=row[3],
            color=row[4],
            account_id=row[5],
        )

    def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, owner_id, discord_channel_id, enabled, color, account_id
                FROM thread
                WHERE owner_id = %s
                ORDER BY thread_id
                """,
                (owner_id,),
            )
            rows = cursor.fetchall()
        return [
            ThreadRecord(
                thread_id=row[0],
                owner_id=row[1],
                discord_channel_id=row[2],
                enabled=row[3],
                color=row[4],
                account_id=row[5],
            )
            for row in rows
        ]

    def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, owner_id, discord_channel_id, enabled, color, account_id
                FROM thread
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            enabled=row[3],
            color=row[4],
            account_id=row[5],
        )

    def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO thread (owner_id, discord_channel_id)
                VALUES (%s, %s)
                RETURNING thread_id, owner_id, discord_channel_id, enabled, color, account_id
                """,
                (owner_id, discord_channel_id),
            )
            row = cursor.fetchone()
        assert row is not None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            enabled=row[3],
            color=row[4],
            account_id=row[5],
        )

    def delete_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM thread
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, enabled, color, account_id
                """,
                (discord_channel_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            enabled=row[3],
            color=row[4],
            account_id=row[5],
        )

    def set_enabled(self, *, discord_channel_id: int, enabled: bool) -> ThreadRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE thread
                SET enabled = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, enabled, color, account_id
                """,
                (enabled, discord_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            enabled=row[3],
            color=row[4],
            account_id=row[5],
        )

    def set_color(self, *, discord_channel_id: int, color: str | None) -> ThreadRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE thread
                SET color = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, enabled, color, account_id
                """,
                (color, discord_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            enabled=row[3],
            color=row[4],
            account_id=row[5],
        )

    def set_account_id(self, *, discord_channel_id: int, account_id: int | None) -> ThreadRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE thread
                SET account_id = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, enabled, color, account_id
                """,
                (account_id, discord_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            enabled=row[3],
            color=row[4],
            account_id=row[5],
        )


@dataclass(slots=True)
class PostgresTwitchAccountRepository(TwitchAccountRepository):
    """Store and retrieve linked Twitch user accounts."""

    database: PostgresDatabase

    def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                       access_token, refresh_token, expires_at, scope, token_type
                FROM twitch_account
                WHERE account_id = %s
                """,
                (account_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_account_record(row)

    def create_account(
        self,
        *,
        discord_user_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO twitch_account (
                    discord_user_id, twitch_user_id, twitch_login, client_id,
                    updated_at, access_token, refresh_token, expires_at, scope, token_type
                )
                VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
                RETURNING account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                          access_token, refresh_token, expires_at, scope, token_type
                """,
                (
                    discord_user_id,
                    twitch_user_id,
                    twitch_login,
                    client_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    Jsonb(list(scope)),
                    token_type,
                ),
            )
            row = cursor.fetchone()
        assert row is not None
        return self._build_account_record(row)

    def update_account(
        self,
        *,
        account_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE twitch_account
                SET twitch_user_id = %s,
                    twitch_login = %s,
                    client_id = %s,
                    updated_at = NOW(),
                    access_token = %s,
                    refresh_token = %s,
                    expires_at = %s,
                    scope = %s,
                    token_type = %s
                WHERE account_id = %s
                RETURNING account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                          access_token, refresh_token, expires_at, scope, token_type
                """,
                (
                    twitch_user_id,
                    twitch_login,
                    client_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    Jsonb(list(scope)),
                    token_type,
                    account_id,
                ),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_account_record(row)

    def remove_by_account_id(self, account_id: int) -> bool:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM twitch_account
                WHERE account_id = %s
                RETURNING account_id
                """,
                (account_id,),
            )
            row = cursor.fetchone()
        return row is not None

    def get_by_discord_user_id(self, discord_user_id: int) -> TwitchAccountRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                       access_token, refresh_token, expires_at, scope, token_type
                FROM twitch_account
                WHERE discord_user_id = %s
                ORDER BY updated_at DESC NULLS LAST, account_id DESC
                LIMIT 1
                """,
                (discord_user_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_account_record(row)

    def upsert_account(
        self,
        *,
        discord_user_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord:
        existing = self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return self.create_account(
                discord_user_id=discord_user_id,
                twitch_user_id=twitch_user_id,
                twitch_login=twitch_login,
                client_id=client_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=scope,
                token_type=token_type,
            )
        updated = self.update_account(
            account_id=existing.account_id,
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login,
            client_id=client_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            token_type=token_type,
        )
        assert updated is not None
        return updated

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        existing = self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return self.remove_by_account_id(existing.account_id)

    @staticmethod
    def _build_account_record(row: tuple) -> TwitchAccountRecord:
        scopes = tuple(row[8] or [])
        return TwitchAccountRecord(
            account_id=int(row[0]),
            discord_user_id=int(row[1]),
            twitch_user_id=row[2],
            twitch_login=row[3],
            client_id=row[4],
            access_token=row[5],
            refresh_token=row[6],
            expires_at=row[7].isoformat() if row[7] is not None else None,
            scope=scopes,
            token_type=row[9],
        )


@dataclass(slots=True)
class PostgresTwitchDeviceFlowRepository(TwitchDeviceFlowRepository):
    """Store and retrieve pending Twitch Device Code authorizations."""

    database: PostgresDatabase

    def get_by_discord_channel_id(self, discord_channel_id: int) -> TwitchDeviceFlowRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                       expires_at, scope, status, last_error, last_polled_at
                FROM twitch_device_flow
                WHERE discord_channel_id = %s
                """,
                (discord_channel_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def upsert_pending_flow(
        self,
        *,
        discord_user_id: int,
        discord_channel_id: int,
        device_code: str,
        user_code: str,
        verification_uri: str,
        interval_seconds: int,
        expires_at: str,
        scope: tuple[str, ...],
    ) -> TwitchDeviceFlowRecord:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO twitch_device_flow (
                    discord_channel_id, discord_user_id, device_code, user_code, verification_uri,
                    interval_seconds, expires_at, scope, status, last_error,
                    last_polled_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', NULL, NULL, NOW())
                ON CONFLICT (discord_channel_id) DO UPDATE SET
                    discord_user_id = EXCLUDED.discord_user_id,
                    device_code = EXCLUDED.device_code,
                    user_code = EXCLUDED.user_code,
                    verification_uri = EXCLUDED.verification_uri,
                    interval_seconds = EXCLUDED.interval_seconds,
                    expires_at = EXCLUDED.expires_at,
                    scope = EXCLUDED.scope,
                    status = 'pending',
                    last_error = NULL,
                    last_polled_at = NULL,
                    updated_at = NOW()
                RETURNING discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                          expires_at, scope, status, last_error, last_polled_at
                """,
                (
                    discord_channel_id,
                    discord_user_id,
                    device_code,
                    user_code,
                    verification_uri,
                    interval_seconds,
                    expires_at,
                    Jsonb(list(scope)),
                ),
            )
            row = cursor.fetchone()
        assert row is not None
        return self._build_record(row)

    def list_pending_flows(self) -> list[TwitchDeviceFlowRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                       expires_at, scope, status, last_error, last_polled_at
                FROM twitch_device_flow
                WHERE status = 'pending'
                ORDER BY discord_channel_id
                """
            )
            rows = cursor.fetchall()
        return [self._build_record(row) for row in rows]

    def mark_failed(self, *, discord_channel_id: int, last_error: str) -> TwitchDeviceFlowRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE twitch_device_flow
                SET status = 'failed',
                    last_error = %s,
                    updated_at = NOW()
                WHERE discord_channel_id = %s
                RETURNING discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                          expires_at, scope, status, last_error, last_polled_at
                """,
                (last_error, discord_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def touch_polled(self, *, discord_channel_id: int) -> None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE twitch_device_flow
                SET last_polled_at = NOW(),
                    updated_at = NOW()
                WHERE discord_channel_id = %s
                """,
                (discord_channel_id,),
            )

    def update_interval(self, *, discord_channel_id: int, interval_seconds: int) -> None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE twitch_device_flow
                SET interval_seconds = %s,
                    updated_at = NOW()
                WHERE discord_channel_id = %s
                """,
                (interval_seconds, discord_channel_id),
            )

    def remove_by_discord_channel_id(self, discord_channel_id: int) -> bool:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM twitch_device_flow
                WHERE discord_channel_id = %s
                RETURNING discord_channel_id
                """,
                (discord_channel_id,),
            )
            row = cursor.fetchone()
        return row is not None

    def get_by_discord_user_id(self, discord_user_id: int) -> TwitchDeviceFlowRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                       expires_at, scope, status, last_error, last_polled_at
                FROM twitch_device_flow
                WHERE discord_user_id = %s
                ORDER BY updated_at DESC, discord_channel_id DESC
                LIMIT 1
                """,
                (discord_user_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        existing = self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return self.remove_by_discord_channel_id(existing.discord_channel_id or 0)

    @staticmethod
    def _build_record(row: tuple) -> TwitchDeviceFlowRecord:
        return TwitchDeviceFlowRecord(
            discord_user_id=int(row[1]),
            discord_channel_id=int(row[0]) if row[0] is not None else None,
            device_code=row[2],
            user_code=row[3],
            verification_uri=row[4],
            interval_seconds=int(row[5]),
            expires_at=row[6].isoformat(),
            scope=tuple(row[7] or []),
            status=row[8],
            last_error=row[9],
            last_polled_at=row[10].isoformat() if row[10] is not None else None,
        )


@dataclass(slots=True)
class PostgresTwitchUserCacheRepository(TwitchUserCacheRepository):
    """Store and retrieve cached Twitch user metadata."""

    database: PostgresDatabase

    def get_by_user_id(self, twitch_user_id: str) -> TwitchUserCacheRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
                FROM twitch_user_cache
                WHERE twitch_user_id = %s
                """,
                (twitch_user_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def get_by_login(self, twitch_login: str) -> TwitchUserCacheRecord | None:
        normalized_login = twitch_login.strip().lower()
        if not normalized_login:
            return None
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
                FROM twitch_user_cache
                WHERE twitch_login = %s
                """,
                (normalized_login,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def upsert_from_api(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str,
        profile_image_url: str | None,
    ) -> TwitchUserCacheRecord:
        normalized_login = twitch_login.strip().lower()
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM twitch_user_cache
                WHERE twitch_login = %s AND twitch_user_id <> %s
                """,
                (normalized_login, twitch_user_id),
            )
            cursor.execute(
                """
                INSERT INTO twitch_user_cache (
                    twitch_user_id,
                    twitch_login,
                    display_name,
                    profile_image_url,
                    updated_at,
                    last_api_refresh_at
                )
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (twitch_user_id)
                DO UPDATE SET
                    twitch_login = EXCLUDED.twitch_login,
                    display_name = EXCLUDED.display_name,
                    profile_image_url = EXCLUDED.profile_image_url,
                    updated_at = CASE
                        WHEN twitch_user_cache.twitch_login IS DISTINCT FROM EXCLUDED.twitch_login
                          OR twitch_user_cache.display_name IS DISTINCT FROM EXCLUDED.display_name
                          OR twitch_user_cache.profile_image_url IS DISTINCT FROM EXCLUDED.profile_image_url
                        THEN NOW()
                        ELSE twitch_user_cache.updated_at
                    END,
                    last_api_refresh_at = NOW()
                RETURNING twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
                """,
                (
                    twitch_user_id,
                    normalized_login,
                    display_name,
                    profile_image_url,
                ),
            )
            row = cursor.fetchone()
        assert row is not None
        return self._build_record(row)

    def observe_from_chat(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str | None,
    ) -> TwitchUserCacheRecord:
        normalized_login = twitch_login.strip().lower()
        normalized_display_name = (display_name or "").strip() or None
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM twitch_user_cache
                WHERE twitch_login = %s AND twitch_user_id <> %s
                """,
                (normalized_login, twitch_user_id),
            )
            cursor.execute(
                """
                INSERT INTO twitch_user_cache (
                    twitch_user_id,
                    twitch_login,
                    display_name,
                    profile_image_url,
                    updated_at,
                    last_api_refresh_at
                )
                VALUES (%s, %s, %s, NULL, NOW(), NULL)
                ON CONFLICT (twitch_user_id)
                DO UPDATE SET
                    twitch_login = EXCLUDED.twitch_login,
                    display_name = COALESCE(%s, twitch_user_cache.display_name, EXCLUDED.display_name),
                    updated_at = CASE
                        WHEN twitch_user_cache.twitch_login IS DISTINCT FROM EXCLUDED.twitch_login
                          OR (%s IS NOT NULL AND twitch_user_cache.display_name IS DISTINCT FROM %s)
                        THEN NOW()
                        ELSE twitch_user_cache.updated_at
                    END
                RETURNING twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
                """,
                (
                    twitch_user_id,
                    normalized_login,
                    normalized_display_name or normalized_login,
                    normalized_display_name,
                    normalized_display_name,
                    normalized_display_name,
                ),
            )
            row = cursor.fetchone()
        assert row is not None
        return self._build_record(row)

    @staticmethod
    def _build_record(row: tuple) -> TwitchUserCacheRecord:
        return TwitchUserCacheRecord(
            twitch_user_id=str(row[0]),
            twitch_login=row[1],
            display_name=row[2],
            profile_image_url=row[3],
            updated_at=row[4].isoformat(),
            last_api_refresh_at=row[5].isoformat() if row[5] is not None else None,
        )


@dataclass(slots=True)
class PostgresChannelRepository(ChannelRepository):
    """Store and retrieve per-thread Twitch channel subscriptions."""

    database: PostgresDatabase

    def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, twitch_channel_id, color, is_live, last_live_status_at
                FROM channel
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ChannelRecord(
            thread_id=row[0],
            twitch_channel_id=row[1],
            color=row[2],
            is_live=row[3],
            last_live_status_at=row[4].isoformat() if row[4] is not None else None,
        )

    def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO channel (thread_id, twitch_channel_id)
                VALUES (%s, %s)
                ON CONFLICT (thread_id, twitch_channel_id) DO NOTHING
                """,
                (thread_id, twitch_channel_id),
            )

    def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM channel
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )

    def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE channel
                SET color = %s
                WHERE thread_id = %s AND twitch_channel_id = %s
                RETURNING thread_id, twitch_channel_id, color, is_live, last_live_status_at
                """,
                (color, thread_id, twitch_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ChannelRecord(
            thread_id=row[0],
            twitch_channel_id=row[1],
            color=row[2],
            is_live=row[3],
            last_live_status_at=row[4].isoformat() if row[4] is not None else None,
        )

    def set_live_state_for_twitch_channel(
        self,
        *,
        twitch_channel_id: str,
        is_live: bool,
        changed_at: str | None,
    ) -> int:
        effective_changed_at = (
            datetime.fromisoformat(changed_at)
            if changed_at is not None
            else datetime.now(timezone.utc)
        )
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE channel
                SET is_live = %s,
                    last_live_status_at = %s
                WHERE twitch_channel_id = %s
                """,
                (is_live, effective_changed_at, twitch_channel_id),
            )
            return cursor.rowcount

    def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM channel
                WHERE twitch_channel_id = %s
                """,
                (twitch_channel_id,),
            )
            row = cursor.fetchone()
        assert row is not None
        return int(row[0])

    def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id
                FROM channel
                WHERE twitch_channel_id = %s
                """,
                (twitch_channel_id,),
            )
            rows = cursor.fetchall()
        return [int(row[0]) for row in rows]

    def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, twitch_channel_id, color, is_live, last_live_status_at
                FROM channel
                WHERE thread_id = %s
                ORDER BY twitch_channel_id
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return [
            ChannelRecord(
                thread_id=row[0],
                twitch_channel_id=row[1],
                color=row[2],
                is_live=row[3],
                last_live_status_at=row[4].isoformat() if row[4] is not None else None,
            )
            for row in rows
        ]

    def list_all_twitch_channel_ids(self) -> list[str]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT twitch_channel_id
                FROM channel
                ORDER BY twitch_channel_id
                """
            )
            rows = cursor.fetchall()
        return [str(row[0]) for row in rows]


@dataclass(slots=True)
class PostgresTrackedUserRepository(TrackedUserRepository):
    """Store and retrieve per-thread tracked Twitch users."""

    database: PostgresDatabase

    def get_by_thread_and_twitch_user(self, thread_id: int, twitch_user_id: str) -> TrackedUserRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, twitch_user_id
                FROM tracked_user
                WHERE thread_id = %s AND twitch_user_id = %s
                """,
                (thread_id, twitch_user_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return TrackedUserRecord(thread_id=row[0], twitch_user_id=row[1])

    def add_user(self, thread_id: int, twitch_user_id: str) -> None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tracked_user (thread_id, twitch_user_id)
                VALUES (%s, %s)
                ON CONFLICT (thread_id, twitch_user_id) DO NOTHING
                """,
                (thread_id, twitch_user_id),
            )

    def remove_user(self, thread_id: int, twitch_user_id: str) -> None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM tracked_user
                WHERE thread_id = %s AND twitch_user_id = %s
                """,
                (thread_id, twitch_user_id),
            )

    def list_users_for_thread(self, thread_id: int) -> list[TrackedUserRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, twitch_user_id
                FROM tracked_user
                WHERE thread_id = %s
                ORDER BY twitch_user_id
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return [TrackedUserRecord(thread_id=row[0], twitch_user_id=row[1]) for row in rows]

    def count_pattern_scope_references(self, *, thread_id: int, twitch_user_id: str) -> int:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM pattern_user_scope
                WHERE thread_id = %s AND twitch_user_id = %s
                """,
                (thread_id, twitch_user_id),
            )
            row = cursor.fetchone()
        assert row is not None
        return int(row[0])


@dataclass(slots=True)
class PostgresPatternRepository(PatternRepository):
    """Store and retrieve ping/regex rules."""

    database: PostgresDatabase

    def find_exact_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
    ) -> PatternRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s
                  AND regex = %s
                  AND channel_scope_mode = %s
                  AND user_scope_mode = %s
                  AND sub_state = %s
                  AND offline_state = %s
                  AND is_regex = %s
                  AND case_sensitive = %s
                """,
                (
                    thread_id,
                    regex,
                    channel_scope_mode,
                    user_scope_mode,
                    sub_state,
                    offline_state,
                    is_regex,
                    case_sensitive,
                ),
            )
            rows = cursor.fetchall()
        normalized_scope_ids = tuple(sorted(channel_scope_ids))
        normalized_user_ids = tuple(sorted(user_scope_ids))
        for row in rows:
            pattern = self._build_pattern_record(row)
            if pattern.channel_scope_ids == normalized_scope_ids and pattern.user_scope_ids == normalized_user_ids:
                return pattern
        return None

    def add_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        disabled: bool,
        priority: int,
    ) -> PatternRecord:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(MAX(p_index), 0) + 1
                FROM pattern
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            next_index_row = cursor.fetchone()
            next_index = int(next_index_row[0]) if next_index_row is not None else 1
            cursor.execute(
                """
                INSERT INTO pattern (
                    thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                    sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                    notify, priority
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                RETURNING thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (
                    thread_id,
                    next_index,
                    regex,
                    channel_scope_mode,
                    user_scope_mode,
                    sub_state,
                    offline_state,
                    is_regex,
                    case_sensitive,
                    color,
                    disabled,
                    priority,
                ),
            )
            row = cursor.fetchone()
            if channel_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_channel_scope (thread_id, p_index, twitch_channel_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, next_index, twitch_channel_id) for twitch_channel_id in channel_scope_ids],
                )
            if user_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_user_scope (thread_id, p_index, twitch_user_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, next_index, twitch_user_id) for twitch_user_id in user_scope_ids],
                )
        assert row is not None
        return self._build_pattern_record(row)

    def remove_pattern(self, *, thread_id: int, p_index: int) -> None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM pattern
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )

    def set_pattern_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> PatternRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pattern
                SET disabled = %s
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (disabled, thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_pattern_record(row)

    def set_pattern_priority(self, *, thread_id: int, p_index: int, priority: int) -> PatternRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pattern
                SET priority = %s
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (priority, thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_pattern_record(row)

    def update_pattern(
        self,
        *,
        thread_id: int,
        p_index: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        priority: int,
    ) -> PatternRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pattern
                SET regex = %s,
                    channel_scope_mode = %s,
                    user_scope_mode = %s,
                    sub_state = %s,
                    offline_state = %s,
                    is_regex = %s,
                    case_sensitive = %s,
                    color = %s,
                    priority = %s
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (
                    regex,
                    channel_scope_mode,
                    user_scope_mode,
                    sub_state,
                    offline_state,
                    is_regex,
                    case_sensitive,
                    color,
                    priority,
                    thread_id,
                    p_index,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                DELETE FROM pattern_channel_scope
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )
            if channel_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_channel_scope (thread_id, p_index, twitch_channel_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, p_index, twitch_channel_id) for twitch_channel_id in channel_scope_ids],
                )
            cursor.execute(
                """
                DELETE FROM pattern_user_scope
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )
            if user_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_user_scope (thread_id, p_index, twitch_user_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, p_index, twitch_user_id) for twitch_user_id in user_scope_ids],
                )
        return self._build_pattern_record(row)

    def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s AND disabled = FALSE AND notify = TRUE
                ORDER BY priority DESC, p_index
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return [self._build_pattern_record(row) for row in rows]

    def get_pattern_by_id(
        self,
        *,
        thread_id: int,
        p_index: int,
    ) -> PatternRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_pattern_record(row)

    def list_patterns_for_thread(
        self,
        thread_id: int,
        *,
        is_regex: bool | None = None,
    ) -> list[PatternRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if is_regex is None:
                cursor.execute(
                    """
                    SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                           sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                           notify, priority
                    FROM pattern
                    WHERE thread_id = %s
                    ORDER BY priority DESC, p_index
                    """,
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                           sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                           notify, priority
                    FROM pattern
                    WHERE thread_id = %s AND is_regex = %s
                    ORDER BY priority DESC, p_index
                    """,
                    (thread_id, is_regex),
                )
            rows = cursor.fetchall()
        return [self._build_pattern_record(row) for row in rows]

    def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM pattern_channel_scope
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )
            row = cursor.fetchone()
        assert row is not None
        return int(row[0])

    def _load_channel_scope_ids(self, *, thread_id: int, p_index: int) -> tuple[str, ...]:
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT twitch_channel_id
                FROM pattern_channel_scope
                WHERE thread_id = %s AND p_index = %s
                ORDER BY twitch_channel_id
                """,
                (thread_id, p_index),
            )
            rows = cursor.fetchall()
        return tuple(str(row[0]) for row in rows)

    def _load_user_scope_ids(self, *, thread_id: int, p_index: int) -> tuple[str, ...]:
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT twitch_user_id
                FROM pattern_user_scope
                WHERE thread_id = %s AND p_index = %s
                ORDER BY twitch_user_id
                """,
                (thread_id, p_index),
            )
            rows = cursor.fetchall()
        return tuple(str(row[0]) for row in rows)

    def _build_pattern_record(self, row: tuple) -> PatternRecord:
        thread_id = int(row[0])
        p_index = int(row[1])
        return PatternRecord(
            thread_id=thread_id,
            p_index=p_index,
            regex=row[2],
            channel_scope_mode=row[3],
            channel_scope_ids=self._load_channel_scope_ids(thread_id=thread_id, p_index=p_index),
            user_scope_mode=row[4],
            user_scope_ids=self._load_user_scope_ids(thread_id=thread_id, p_index=p_index),
            sub_state=row[5],
            offline_state=row[6],
            is_regex=row[7],
            case_sensitive=row[8],
            color=row[9],
            disabled=row[10],
            notify=row[11],
            priority=int(row[12]),
        )


@dataclass(slots=True)
class PostgresReplyRepository(ReplyRepository):
    """Store and retrieve auto-replies attached to patterns."""

    database: PostgresDatabase

    def get_by_pattern(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, p_index, reply_message, reply_as_reply, disabled
                FROM reply
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def add_reply(
        self,
        *,
        thread_id: int,
        p_index: int,
        reply_message: str,
        reply_as_reply: bool,
    ) -> ReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO reply (thread_id, p_index, reply_message, reply_as_reply, disabled)
                VALUES (%s, %s, %s, %s, FALSE)
                ON CONFLICT (thread_id, p_index) DO NOTHING
                RETURNING thread_id, p_index, reply_message, reply_as_reply, disabled
                """,
                (thread_id, p_index, reply_message, reply_as_reply),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def remove_reply(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM reply
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, reply_message, reply_as_reply, disabled
                """,
                (thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def set_reply_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> ReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = %s
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, reply_message, reply_as_reply, disabled
                """,
                (disabled, thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ReplyRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT thread_id, p_index, reply_message, reply_as_reply, disabled
                    FROM reply
                    WHERE thread_id = %s
                    ORDER BY p_index
                    """,
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT thread_id, p_index, reply_message, reply_as_reply, disabled
                    FROM reply
                    WHERE thread_id = %s AND disabled = FALSE
                    ORDER BY p_index
                    """,
                    (thread_id,),
                )
            rows = cursor.fetchall()
        return [self._build_reply_record(row) for row in rows]

    def disable_replies_for_thread(self, thread_id: int) -> int:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = TRUE
                WHERE thread_id = %s AND disabled = FALSE
                RETURNING p_index
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return len(rows)

    def enable_replies_for_thread(self, thread_id: int) -> int:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = FALSE
                WHERE thread_id = %s AND disabled = TRUE
                RETURNING p_index
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return len(rows)

    @staticmethod
    def _build_reply_record(row: tuple) -> ReplyRecord:
        return ReplyRecord(
            thread_id=int(row[0]),
            p_index=int(row[1]),
            reply_message=row[2],
            reply_as_reply=row[3],
            disabled=row[4],
        )


@dataclass(slots=True)
class PostgresChannelEventReplyRepository(ChannelEventReplyRepository):
    """Store and retrieve auto-replies triggered by live/offline channel events."""

    database: PostgresDatabase

    def get_by_channel_event(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
    ) -> ChannelEventReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, twitch_channel_id, event_state, reply_message, disabled
                FROM channel_event_reply
                WHERE thread_id = %s AND twitch_channel_id = %s AND event_state = %s
                """,
                (thread_id, twitch_channel_id, event_state),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def upsert_reply(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
        reply_message: str,
    ) -> ChannelEventReplyRecord:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO channel_event_reply (thread_id, twitch_channel_id, event_state, reply_message, disabled)
                VALUES (%s, %s, %s, %s, FALSE)
                ON CONFLICT (thread_id, twitch_channel_id, event_state)
                DO UPDATE SET
                    reply_message = EXCLUDED.reply_message,
                    disabled = FALSE
                RETURNING thread_id, twitch_channel_id, event_state, reply_message, disabled
                """,
                (thread_id, twitch_channel_id, event_state, reply_message),
            )
            row = cursor.fetchone()
        assert row is not None
        return self._build_record(row)

    def remove_reply(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
    ) -> ChannelEventReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM channel_event_reply
                WHERE thread_id = %s AND twitch_channel_id = %s AND event_state = %s
                RETURNING thread_id, twitch_channel_id, event_state, reply_message, disabled
                """,
                (thread_id, twitch_channel_id, event_state),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def set_reply_disabled(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
        disabled: bool,
    ) -> ChannelEventReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE channel_event_reply
                SET disabled = %s
                WHERE thread_id = %s AND twitch_channel_id = %s AND event_state = %s
                RETURNING thread_id, twitch_channel_id, event_state, reply_message, disabled
                """,
                (disabled, thread_id, twitch_channel_id, event_state),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def list_replies_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[ChannelEventReplyRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT thread_id, twitch_channel_id, event_state, reply_message, disabled
                    FROM channel_event_reply
                    WHERE thread_id = %s
                    ORDER BY event_state, twitch_channel_id
                    """,
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT thread_id, twitch_channel_id, event_state, reply_message, disabled
                    FROM channel_event_reply
                    WHERE thread_id = %s AND disabled = FALSE
                    ORDER BY event_state, twitch_channel_id
                    """,
                    (thread_id,),
                )
            rows = cursor.fetchall()
        return [self._build_record(row) for row in rows]

    def list_replies_for_channel_event(
        self,
        *,
        twitch_channel_id: str,
        event_state: str,
        include_disabled: bool = False,
    ) -> list[ChannelEventReplyRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT thread_id, twitch_channel_id, event_state, reply_message, disabled
                    FROM channel_event_reply
                    WHERE twitch_channel_id = %s AND event_state = %s
                    ORDER BY thread_id
                    """,
                    (twitch_channel_id, event_state),
                )
            else:
                cursor.execute(
                    """
                    SELECT thread_id, twitch_channel_id, event_state, reply_message, disabled
                    FROM channel_event_reply
                    WHERE twitch_channel_id = %s AND event_state = %s AND disabled = FALSE
                    ORDER BY thread_id
                    """,
                    (twitch_channel_id, event_state),
                )
            rows = cursor.fetchall()
        return [self._build_record(row) for row in rows]

    @staticmethod
    def _build_record(row: tuple) -> ChannelEventReplyRecord:
        return ChannelEventReplyRecord(
            thread_id=int(row[0]),
            twitch_channel_id=str(row[1]),
            event_state=row[2],
            reply_message=row[3],
            disabled=bool(row[4]),
        )


@dataclass(slots=True)
class PostgresUserPermissionRepository(UserPermissionRepository):
    """Store and retrieve additional per-thread Discord permission grants."""

    database: PostgresDatabase

    def get_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> UserPermissionRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT discord_user_id, thread_id, permissions
                FROM user_permissions
                WHERE discord_user_id = %s AND thread_id = %s
                """,
                (discord_user_id, thread_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return UserPermissionRecord(discord_user_id=int(row[0]), thread_id=int(row[1]), permissions=int(row[2]))

    def upsert_permissions(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
        permissions: int,
    ) -> UserPermissionRecord:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_permissions (discord_user_id, thread_id, permissions)
                VALUES (%s, %s, %s)
                ON CONFLICT (discord_user_id, thread_id)
                DO UPDATE SET permissions = EXCLUDED.permissions
                RETURNING discord_user_id, thread_id, permissions
                """,
                (discord_user_id, thread_id, permissions),
            )
            row = cursor.fetchone()
        assert row is not None
        return UserPermissionRecord(discord_user_id=int(row[0]), thread_id=int(row[1]), permissions=int(row[2]))

    def remove_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> bool:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM user_permissions
                WHERE discord_user_id = %s AND thread_id = %s
                RETURNING discord_user_id
                """,
                (discord_user_id, thread_id),
            )
            row = cursor.fetchone()
        return row is not None

    def list_for_thread(self, *, thread_id: int) -> list[UserPermissionRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT discord_user_id, thread_id, permissions
                FROM user_permissions
                WHERE thread_id = %s
                ORDER BY discord_user_id
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return [
            UserPermissionRecord(discord_user_id=int(row[0]), thread_id=int(row[1]), permissions=int(row[2]))
            for row in rows
        ]
