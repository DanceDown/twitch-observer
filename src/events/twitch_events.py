"""Normalized Twitch runtime events and typed stream keys."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class StreamEventKind(StrEnum):
    """Typed tracked external stream event keys."""

    ONLINE = "stream.online"
    OFFLINE = "stream.offline"

    @property
    def state_name(self) -> str:
        return "online" if self is StreamEventKind.ONLINE else "offline"


@dataclass(slots=True, frozen=True)
class TwitchChatMessageEvent:
    """Normalized representation of a Twitch chat message received by the app."""

    channel_login: str
    author_login: str
    content: str
    author_display_name: str | None = None
    message_id: str | None = None
    broadcaster_id: str | None = None
    author_id: str | None = None
    color: str | None = None
    reply_parent_message_id: str | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw_line: str | None = None
    raw_tags: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class TwitchChannelLiveStateChangedEvent:
    """Domain event emitted when a tracked Twitch channel changes live status."""

    twitch_channel_id: str
    is_live: bool
    twitch_channel_login: str | None = None
    changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
