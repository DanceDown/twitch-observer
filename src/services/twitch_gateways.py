"""Explicit Twitch and IRC service protocols used by the domain services."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.events.twitch_events import TwitchChatSendRequest
from src.gateways.twitch_api import TwitchDeviceCodeStart, TwitchDevicePollResult, TwitchUser, TwitchUserTokenBundle, TwitchValidatedToken


class TwitchUserLookup(Protocol):
    """Lookup Twitch users with cache-aware read methods."""

    async def get_user_by_login(self, login: str) -> TwitchUser:
        """Return a Twitch user for a login, using cache when possible."""
        ...

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        """Refresh a Twitch user for a login from the upstream API."""
        ...

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        """Return a Twitch user for an ID, using cache when possible."""
        ...

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        """Refresh a Twitch user for an ID from the upstream API."""
        ...

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        """Return an in-memory cached user for a login without I/O."""
        ...

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        """Return an in-memory cached user for an ID without I/O."""
        ...

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None:
        """Load a persisted cached user for a login without upstream calls."""
        ...

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        """Load a persisted cached user for an ID without upstream calls."""
        ...

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        """Return many Twitch users for IDs, using the normal metadata path."""
        ...


@runtime_checkable
class TwitchUserChatColorLookup(Protocol):
    """Optional Twitch lookup extension for caller paths that need chat-name colors."""

    async def get_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        """Return a user by login and include Twitch chat-name color metadata."""
        ...

    async def refresh_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        """Refresh a user by login and include Twitch chat-name color metadata."""
        ...

    async def get_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        """Return a user by ID and include Twitch chat-name color metadata."""
        ...

    async def refresh_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        """Refresh a user by ID and include Twitch chat-name color metadata."""
        ...


class TwitchChannelLookup(Protocol):
    """Resolve broadcaster/channel metadata."""

    async def get_user_by_login(self, login: str) -> TwitchUser:
        """Return a broadcaster by login, using cache when possible."""
        ...

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        """Refresh a broadcaster by login from the upstream API."""
        ...

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        """Return broadcaster metadata for a Twitch user ID."""
        ...


class TwitchDirectoryGateway(TwitchUserLookup, TwitchChannelLookup, Protocol):
    """Combined lookup contract for services that need both user and channel metadata."""


class TwitchAuthGateway(Protocol):
    """Run Twitch device-code and token workflows."""

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        """Validate a user access token and return the inspected token claims."""
        ...

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart:
        """Start a Twitch device-code login flow for the requested scopes."""
        ...

    async def poll_device_code_flow(self, *, device_code: str, scopes: tuple[str, ...]) -> TwitchDevicePollResult:
        """Poll one Twitch device-code flow until it is pending, ready, or failed."""
        ...

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle:
        """Refresh a Twitch user access token with a refresh token."""
        ...


class TwitchChatGateway(Protocol):
    """Send Twitch chat messages."""

    async def send_chat_message(self, request: TwitchChatSendRequest) -> str:
        """Send one Twitch chat message and return Twitch's message ID."""
        ...


class TwitchLiveGateway(Protocol):
    """Query live-state for broadcasters."""

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        """Return the subset of Twitch user IDs that are currently live."""
        ...


class TwitchLiveMonitorGateway(TwitchLiveGateway, TwitchUserLookup, Protocol):
    """Combined live-state and user-resolution contract for the live monitor."""


class TwitchAccountGateway(TwitchAuthGateway, TwitchUserLookup, Protocol):
    """Combined contract used by account-link and device-flow services."""


class TwitchReplyGateway(TwitchChatGateway, TwitchAuthGateway, TwitchUserLookup, Protocol):
    """Combined Twitch contract used by reply execution services."""


class TwitchChannelStateLookup(TwitchChannelLookup, TwitchUserLookup, Protocol):
    """Combined lookup contract for channel-event configuration services."""


class TwitchIRCChannelGateway(Protocol):
    """Twitch IRC gateway methods consumed by services."""

    async def ensure_connected(self) -> None:
        """Ensure the IRC connection exists before channel operations."""
        ...

    async def join_channel(self, channel_login: str) -> None:
        """Join one Twitch IRC channel by login."""
        ...

    async def join_channels(self, channel_logins: list[str]) -> None:
        """Join multiple Twitch IRC channels by login."""
        ...

    async def leave_channel(self, channel_login: str) -> None:
        """Leave one Twitch IRC channel by login."""
        ...

    async def leave_channels(self, channel_logins: list[str]) -> None:
        """Leave multiple Twitch IRC channels by login."""
        ...


class TwitchIRCConnectionGateway(TwitchIRCChannelGateway, Protocol):
    """Twitch IRC gateway methods needed by startup/runtime workers."""

    async def wait_until_connected(self) -> None:
        """Wait until IRC has completed its initial connection."""
        ...
