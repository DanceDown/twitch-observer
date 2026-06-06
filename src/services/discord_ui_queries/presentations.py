"""Immutable presentation models for Discord UI query results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.database.connection import AdapterEventActionRecord, AdapterEventRecord, PatternRecord, ReplyRecord


@dataclass(slots=True, frozen=True)
class TrackedChannelPresentation:
    user_id: str
    login: str
    display_name: str
    color: str | None


@dataclass(slots=True, frozen=True)
class PatternPresentation:
    display_index: int
    pattern: PatternRecord
    channel_logins: tuple[str, ...]
    channel_display_names: tuple[str, ...]
    user_logins: tuple[str, ...]
    user_display_names: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ReplyPresentation:
    reply: ReplyRecord
    pattern: PatternPresentation


@dataclass(slots=True, frozen=True)
class AdapterEventPresentation:
    event: AdapterEventRecord
    channel: TrackedChannelPresentation


@dataclass(slots=True, frozen=True)
class AdapterEventActionPresentation:
    event: AdapterEventPresentation
    action: AdapterEventActionRecord
    display_index: int | None = None


@dataclass(slots=True, frozen=True)
class TrackedUserPresentation:
    user_id: str
    login: str
    display_name: str


@dataclass(slots=True, frozen=True)
class WriteReplyCandidatePresentation:
    message_id: str
    twitch_channel_id: str
    username: str
    content: str
    timestamp: datetime
