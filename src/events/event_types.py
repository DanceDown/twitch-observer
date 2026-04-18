from __future__ import annotations

"""Typed event declarations shared across adapters and services."""

from asyncio import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class EventType(StrEnum):
    """Canonical event names published on the in-process event bus."""

    DISCORD_THREAD_REQUESTED = "discord.thread.requested"
    DISCORD_CHANNEL_REQUESTED = "discord.channel.requested"
    DISCORD_USER_REQUESTED = "discord.user.requested"
    DISCORD_PATTERN_REQUESTED = "discord.pattern.requested"
    DISCORD_PATTERN_EDIT_REQUESTED = "discord.pattern.edit.requested"
    DISCORD_ACCOUNT_REQUESTED = "discord.account.requested"
    DISCORD_REPLY_REQUESTED = "discord.reply.requested"
    DISCORD_PERMISSION_REQUESTED = "discord.permission.requested"
    DISCORD_WRITE_REQUESTED = "discord.write.requested"
    DISCORD_SHOW_REQUESTED = "discord.show.requested"
    TWITCH_CHAT_MESSAGE = "twitch.chat.message"


class DiscordResultStyle(StrEnum):
    """Presentation style for Discord embeds."""

    SUCCESS = "success"
    ERROR = "error"
    INFO = "info"


@dataclass(slots=True, frozen=True)
class DiscordCommandResult:
    """Result of a Discord-triggered command handling pipeline."""

    title: str
    message: str
    style: DiscordResultStyle = DiscordResultStyle.INFO
    ephemeral: bool = False


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
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_line: str | None = None
    raw_tags: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DiscordThreadRequestedEvent:
    """Normalized command event for joining or leaving one Discord context."""

    discord_channel_id: int
    requester_id: int
    action: str
    result_future: Future[DiscordCommandResult]
    color: str | None = None
    clear_color: bool = False


@dataclass(slots=True, frozen=True)
class DiscordChannelRequestedEvent:
    """Normalized command event for adding or removing a tracked Twitch channel."""

    discord_channel_id: int
    requester_id: int
    action: str
    twitch_channel_login: str
    result_future: Future[DiscordCommandResult]
    color: str | None = None
    clear_color: bool = False


@dataclass(slots=True, frozen=True)
class DiscordUserRequestedEvent:
    """Normalized command event for adding or removing tracked Twitch users."""

    discord_channel_id: int
    requester_id: int
    action: str
    twitch_user_login: str
    result_future: Future[DiscordCommandResult]


@dataclass(slots=True, frozen=True)
class DiscordPatternRequestedEvent:
    """Normalized command event for adding or removing a ping/regex pattern."""

    discord_channel_id: int
    requester_id: int
    action: str
    pattern_text: str | None
    pattern_id: int | None
    is_regex: bool | None
    channel_scope_mode: str
    twitch_channel_logins: tuple[str, ...]
    user_scope_mode: str
    twitch_user_logins: tuple[str, ...]
    sub_state: str
    offline_state: str
    case_sensitive: bool
    color: str | None
    disabled: bool
    result_future: Future[DiscordCommandResult]

@dataclass(slots=True, frozen=True)
class DiscordPatternEditRequestedEvent:
    """Normalized command event for editing an existing ping or regex pattern."""

    discord_channel_id: int
    requester_id: int
    pattern_id: int
    pattern_text: str | None
    is_regex: bool | None
    channel_scope_mode: str | None
    twitch_channel_logins: tuple[str, ...] | None
    user_scope_mode: str | None
    twitch_user_logins: tuple[str, ...] | None
    sub_state: str | None
    offline_state: str | None
    case_sensitive: bool | None
    color: str | None
    clear_color: bool
    priority: int | None
    result_future: Future[DiscordCommandResult]


@dataclass(slots=True, frozen=True)
class DiscordAccountRequestedEvent:
    """Normalized command event for linking or unlinking a Twitch account."""

    requester_id: int
    discord_channel_id: int | None
    action: str
    result_future: Future[DiscordCommandResult]


@dataclass(slots=True, frozen=True)
class DiscordReplyRequestedEvent:
    """Normalized command event for adding or removing a reply on one pattern."""

    discord_channel_id: int
    requester_id: int
    action: str
    pattern_id: int
    message: str | None
    reply_as_reply: bool
    result_future: Future[DiscordCommandResult]


@dataclass(slots=True, frozen=True)
class DiscordPermissionRequestedEvent:
    """Normalized command event for granting or revoking thread permissions."""

    discord_channel_id: int
    requester_id: int
    action: str
    target_user_id: int
    permissions: tuple[str, ...] | None
    result_future: Future[DiscordCommandResult]


@dataclass(slots=True, frozen=True)
class DiscordWriteRequestedEvent:
    """Normalized command event for manually sending one Twitch chat message."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_login: str
    message: str
    reply_parent_message_id: str | None
    result_future: Future[DiscordCommandResult]


@dataclass(slots=True, frozen=True)
class DiscordShowRequestedEvent:
    """Normalized slash command event for showing stored configuration sections."""

    discord_channel_id: int
    requester_id: int
    sections: tuple[str, ...]
    result_future: Future[DiscordCommandResult]
