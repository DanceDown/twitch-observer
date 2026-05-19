"""Typed input and event declarations shared across entrypoints and services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class DiscordResultStyle(StrEnum):
    """Presentation style for Discord embeds."""

    SUCCESS = "success"
    ERROR = "error"
    INFO = "info"


class ChannelScopeMode(StrEnum):
    """Typed pattern channel scope selectors."""

    ALL_TRACKED = "all_tracked"
    ONLY_SELECTED = "only_selected"
    ALL_EXCEPT_SELECTED = "all_except_selected"


class UserScopeMode(StrEnum):
    """Typed pattern user scope selectors."""

    ALL_USERS = "all_users"
    ALL_TRACKED = "all_tracked"
    ONLY_SELECTED = "only_selected"
    ALL_EXCEPT_SELECTED = "all_except_selected"
    ALL_TRACKED_EXCEPT_SELECTED = "all_tracked_except_selected"


class SubscriptionScope(StrEnum):
    """Typed subscriber-state filters."""

    ALL = "all"
    NON_SUBS = "non_subs"
    SUBS = "subs"


class OfflineScope(StrEnum):
    """Typed live/offline filters."""

    BOTH = "both"
    OFFLINE = "offline"
    ONLINE = "online"


class ReplyTargetKind(StrEnum):
    """Typed reply target kinds."""

    PATTERN = "pattern"
    ADAPTER_EVENT = "adapter_event"


class UIFlowKind(StrEnum):
    """Top-level Discord UI flows."""

    THREAD = "thread"
    CHANNEL = "channel"
    USER = "user"
    SHOW = "show"
    PERMISSION = "permission"
    ACCOUNT = "account"
    LIVE = "live"
    OFFLINE = "offline"
    WRITE = "write"
    PATTERN = "ping"
    REPLY = "reply"


class UIFlowStep(StrEnum):
    """Typed Discord UI flow steps."""

    ROOT = "root"
    REMOVE = "remove"
    LEAVE = "leave"
    COLOR = "color"
    ADD_PATTERN = "add_pattern"
    ADD_EVENT = "add_event"
    ENABLE = "enable"
    DISABLE = "disable"


class TrackedChannelsChangeReason(StrEnum):
    """Reasons for tracked-channel invalidation events."""

    CHANNEL_ADDED = "channel_added"
    CHANNEL_REMOVED = "channel_removed"
    THREAD_LEFT = "thread_left"


class StreamEventKind(StrEnum):
    """Typed tracked external stream event keys."""

    ONLINE = "stream.online"
    OFFLINE = "stream.offline"

    @property
    def state_name(self) -> str:
        return "online" if self is StreamEventKind.ONLINE else "offline"


@dataclass(slots=True, frozen=True)
class DiscordCommandResult:
    """Result of a Discord-triggered command handling pipeline."""

    title: str
    message: str
    style: DiscordResultStyle = DiscordResultStyle.INFO
    ephemeral: bool = False
    thumbnail_url: str | None = None


@dataclass(slots=True, frozen=True)
class DiscordUIFlowDecision:
    """Decision for opening the next Discord UI step."""

    flow: UIFlowKind
    step: UIFlowStep
    open_ui: bool
    result: DiscordCommandResult | None = None


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
class ShowAccountCommand:
    """Return the account-help result for the moved `/show account` flow."""

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
class SetChannelEventEnabledCommand:
    """Enable or disable one tracked live/offline event configuration."""

    discord_channel_id: int
    requester_id: int
    twitch_channel_id: str
    event_kind: StreamEventKind
    enabled: bool


@dataclass(slots=True, frozen=True)
class ShowConfigurationCommand:
    """Render one configuration overview for the active Discord context."""

    discord_channel_id: int
    requester_id: int
    sections: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class RequestUIFlowCommand:
    """Request a service-owned decision before opening a Discord UI step."""

    discord_channel_id: int | None
    requester_id: int
    flow: UIFlowKind
    step: UIFlowStep


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
class TwitchTrackedChannelsChangedEvent:
    """Domain event emitted whenever the set of tracked Twitch channels changes."""

    reason: TrackedChannelsChangeReason


@dataclass(slots=True, frozen=True)
class TwitchChannelLiveStateChangedEvent:
    """Domain event emitted when a tracked Twitch channel changes live status."""

    twitch_channel_id: str
    is_live: bool
    twitch_channel_login: str | None = None
    changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
