"""Shared PostgreSQL record dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class ThreadRecord:
    """Persisted Discord channel configuration root."""

    thread_id: int
    owner_id: int
    discord_channel_id: int
    enabled: bool
    color: str | None
    language: str = "english"
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


@dataclass(slots=True, frozen=True)
class ChannelRecord:
    """Persisted Twitch channel subscription for one thread."""

    thread_id: int
    twitch_channel_id: str
    color: str | None
    is_live: bool | None = None
    last_live_status_at: str | None = None


@dataclass(slots=True, frozen=True)
class TrackedChannelStateRecord:
    """Distinct tracked Twitch channel plus its persisted live state."""

    twitch_channel_id: str
    is_live: bool | None
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
    pattern_id: int
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
    priority: int
    reply_message: str | None = None
    reply_as_reply: bool = False


@dataclass(slots=True, frozen=True)
class ReplyRecord:
    """Persisted auto-reply attached to one pattern."""

    thread_id: int
    pattern_id: int
    reply_message: str
    reply_as_reply: bool
    disabled: bool


@dataclass(slots=True, frozen=True)
class ChatPatternSeedRecord:
    """Slim hot-path seed used before Python content matching."""

    thread_id: int
    pattern_id: int
    regex: str
    is_regex: bool
    case_sensitive: bool
    priority: int
    explicit_user_scope_match: bool


@dataclass(slots=True, frozen=True)
class ChatPatternCandidateRecord:
    """Pre-filtered hot-path pattern candidate for one incoming Twitch chat message."""

    thread: ThreadRecord
    source_channel: ChannelRecord
    pattern: PatternRecord
    reply: ReplyRecord | None
    explicit_user_scope_match: bool


@dataclass(slots=True, frozen=True)
class AdapterEventRecord:
    """Persisted external adapter event trigger for one thread."""

    event_id: int
    thread_id: int
    adapter_key: str
    subject_type: str
    subject_id: str
    event_key: str
    disabled: bool


@dataclass(slots=True, frozen=True)
class AdapterEventActionRecord:
    """Persisted follow-up action attached to one external adapter event."""

    event_id: int
    action_type: str
    message_template: str | None
    reply_as_reply: bool
    color: str | None
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

    message_id: str
    twitch_channel_id: str
    username: str
    content: str
    timestamp: datetime
