"""Immutable presentation models for Discord UI query results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.database.connection import AdapterEventActionRecord, AdapterEventRecord, PatternRecord, ReplyRecord


@dataclass(slots=True, frozen=True)
class TrackedChannelPresentation:
    """Twitch channel data ready for Discord selects and show output."""

    user_id: str
    login: str
    display_name: str
    color: str | None


@dataclass(slots=True, frozen=True)
class PatternPresentation:
    """Pattern record plus resolved display names for Discord UIs."""

    display_index: int
    pattern: PatternRecord
    channel_logins: tuple[str, ...]
    channel_display_names: tuple[str, ...]
    user_logins: tuple[str, ...]
    user_display_names: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ReplyPresentation:
    """Pattern auto-reply paired with its rendered pattern data."""

    reply: ReplyRecord
    pattern: PatternPresentation


@dataclass(slots=True, frozen=True)
class AdapterEventPresentation:
    """External event trigger paired with its Twitch channel display data."""

    event: AdapterEventRecord
    channel: TrackedChannelPresentation


@dataclass(slots=True, frozen=True)
class AdapterEventActionPresentation:
    """External event action plus optional user-facing display index."""

    event: AdapterEventPresentation
    action: AdapterEventActionRecord
    display_index: int | None = None


@dataclass(slots=True, frozen=True)
class TrackedUserPresentation:
    """Twitch user data ready for Discord selects and show output."""

    user_id: str
    login: str
    display_name: str


@dataclass(slots=True, frozen=True)
class WriteReplyCandidatePresentation:
    """Recent Twitch message that can be selected as a `/write` reply target."""

    message_id: str
    twitch_channel_id: str
    username: str
    content: str
    timestamp: datetime
