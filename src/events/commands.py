"""Typed command payloads shared between Discord entrypoints and services."""

from __future__ import annotations

from dataclasses import dataclass

from .pattern_scopes import ChannelScopeMode, OfflineScope, SubscriptionScope, UserScopeMode
from .twitch_events import StreamEventKind


@dataclass(slots=True, frozen=True)
class JoinThreadCommand:
    """Create a new Discord observer context."""

    discord_channel_id: int
    requester_id: int


@dataclass(slots=True, frozen=True)
class LeaveThreadCommand:
    """Delete one Discord observer context."""

    discord_channel_id: int
    requester_id: int


@dataclass(slots=True, frozen=True)
class SetThreadEnabledCommand:
    """Enable or disable one Discord observer context."""

    discord_channel_id: int
    requester_id: int
    enabled: bool


@dataclass(slots=True, frozen=True)
class SetThreadColorCommand:
    """Set or clear the default color for one Discord observer context."""

    discord_channel_id: int
    requester_id: int
    color: str | None


@dataclass(slots=True, frozen=True)
class SetThreadLanguageCommand:
    """Set the active localization language for one Discord observer context."""

    discord_channel_id: int
    requester_id: int
    language: str


@dataclass(slots=True, frozen=True)
class AddTrackedChannelCommand:
    """Track one Twitch channel for the active Discord context."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_login: str


@dataclass(slots=True, frozen=True)
class RemoveTrackedChannelCommand:
    """Remove one tracked Twitch channel from the active Discord context."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_login: str


@dataclass(slots=True, frozen=True)
class SetTrackedChannelColorCommand:
    """Set or clear the Discord embed color for one tracked Twitch channel."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_login: str
    color: str | None


@dataclass(slots=True, frozen=True)
class AddTrackedUserCommand:
    """Track one Twitch user for the active Discord context."""

    discord_channel_id: int
    requester_id: int
    twitch_user_login: str


@dataclass(slots=True, frozen=True)
class RemoveTrackedUserCommand:
    """Remove one tracked Twitch user from the active Discord context."""

    discord_channel_id: int
    requester_id: int
    twitch_user_login: str


@dataclass(slots=True, frozen=True)
class AddPatternCommand:
    """Create one message-driven ping/regex pattern."""

    discord_channel_id: int
    requester_id: int
    pattern_text: str
    is_regex: bool
    channel_scope_mode: ChannelScopeMode
    twitch_channel_logins: tuple[str, ...]
    user_scope_mode: UserScopeMode
    twitch_user_logins: tuple[str, ...]
    sub_state: SubscriptionScope
    offline_state: OfflineScope
    case_sensitive: bool
    color: str | None
    disabled: bool
    priority: int | None


@dataclass(slots=True, frozen=True)
class RemovePatternCommand:
    """Remove one existing message-driven pattern."""

    discord_channel_id: int
    requester_id: int
    pattern_id: int


@dataclass(slots=True, frozen=True)
class SetPatternEnabledCommand:
    """Enable or disable one existing message-driven pattern."""

    discord_channel_id: int
    requester_id: int
    pattern_id: int
    enabled: bool


@dataclass(slots=True, frozen=True)
class EditPatternCommand:
    """Edit one existing message-driven pattern."""

    discord_channel_id: int
    requester_id: int
    pattern_id: int
    pattern_text: str | None
    is_regex: bool | None
    channel_scope_mode: ChannelScopeMode | None
    twitch_channel_logins: tuple[str, ...] | None
    user_scope_mode: UserScopeMode | None
    twitch_user_logins: tuple[str, ...] | None
    sub_state: SubscriptionScope | None
    offline_state: OfflineScope | None
    case_sensitive: bool | None
    color: str | None
    clear_color: bool
    priority: int | None


@dataclass(slots=True, frozen=True)
class StartAccountLinkCommand:
    """Start Twitch device-code linking for the active Discord context."""

    requester_id: int
    discord_channel_id: int | None


@dataclass(slots=True, frozen=True)
class UnlinkAccountCommand:
    """Unlink the Twitch account from the active Discord context."""

    requester_id: int
    discord_channel_id: int | None


@dataclass(slots=True, frozen=True)
class AddPatternReplyCommand:
    """Attach one auto-reply to an existing pattern."""

    discord_channel_id: int
    requester_id: int
    pattern_id: int
    message: str
    reply_as_reply: bool


@dataclass(slots=True, frozen=True)
class RemovePatternReplyCommand:
    """Remove one pattern-bound auto-reply."""

    discord_channel_id: int
    requester_id: int
    pattern_id: int


@dataclass(slots=True, frozen=True)
class SetPatternReplyEnabledCommand:
    """Enable or disable one pattern-bound auto-reply."""

    discord_channel_id: int
    requester_id: int
    pattern_id: int
    enabled: bool


@dataclass(slots=True, frozen=True)
class AddChannelEventReplyCommand:
    """Attach one auto-reply action to a tracked external event."""

    discord_channel_id: int
    requester_id: int
    adapter_event_id: int
    message: str
    reply_as_reply: bool


@dataclass(slots=True, frozen=True)
class RemoveChannelEventReplyCommand:
    """Remove one event-bound auto-reply action."""

    discord_channel_id: int
    requester_id: int
    adapter_event_id: int


@dataclass(slots=True, frozen=True)
class SetChannelEventReplyEnabledCommand:
    """Enable or disable one event-bound auto-reply action."""

    discord_channel_id: int
    requester_id: int
    adapter_event_id: int
    enabled: bool


@dataclass(slots=True, frozen=True)
class GrantPermissionsCommand:
    """Grant one or more permissions inside the active Discord context."""

    discord_channel_id: int
    requester_id: int
    target_user_id: int
    permissions: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class RevokePermissionsCommand:
    """Revoke one or more permissions inside the active Discord context."""

    discord_channel_id: int
    requester_id: int
    target_user_id: int
    permissions: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ClearPermissionsCommand:
    """Remove all explicit permissions for one user inside the active context."""

    discord_channel_id: int
    requester_id: int
    target_user_id: int


@dataclass(slots=True, frozen=True)
class SendTwitchMessageCommand:
    """Send one manual Twitch chat message."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_login: str
    message: str
    reply_parent_message_id: str | None


@dataclass(slots=True, frozen=True)
class AddChannelEventCommand:
    """Enable one tracked live/offline event for a tracked Twitch channel."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_id: str
    event_kind: StreamEventKind


@dataclass(slots=True, frozen=True)
class RemoveChannelEventCommand:
    """Disable one tracked live/offline event for a tracked Twitch channel."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_id: str
    event_kind: StreamEventKind


@dataclass(slots=True, frozen=True)
class SetChannelEventColorCommand:
    """Set or clear the Discord embed color for one tracked live/offline ping."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_id: str
    event_kind: StreamEventKind
    color: str | None


@dataclass(slots=True, frozen=True)
class ShowConfigurationCommand:
    """Render one configuration overview for the active Discord context."""

    discord_channel_id: int
    requester_id: int
    sections: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class CreateSupportTicketCommand:
    """Create one support ticket from a Discord context."""

    discord_channel_id: int
    requester_id: int
    category: str
    title: str
    description: str
    language_hint: str | None


@dataclass(slots=True, frozen=True)
class AnswerSupportTicketCommand:
    """Answer one open support ticket."""

    ticket_id: int
    responder_id: int
    subject: str
    body: str


@dataclass(slots=True, frozen=True)
class CloseSupportTicketCommand:
    """Close one open support ticket without answering it."""

    ticket_id: int
    closer_id: int


@dataclass(slots=True, frozen=True)
class ShowSupportTicketCommand:
    """Render configuration for the Discord context attached to one support ticket."""

    ticket_id: int
    requester_id: int
    sections: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class HelpCommand:
    """Render one beginner-friendly help section."""

    discord_channel_id: int | None
    requester_id: int
    language_hint: str | None
    section: str | None
