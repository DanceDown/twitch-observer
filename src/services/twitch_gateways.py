"""Explicit Twitch and IRC service protocols used by the domain services."""

from __future__ import annotations

from typing import Protocol

from src.gateways.twitch_api import TwitchDeviceCodeStart, TwitchDevicePollResult, TwitchUser, TwitchUserTokenBundle, TwitchValidatedToken


class TwitchUserLookup(Protocol):
    """Lookup Twitch users with cache-aware read methods."""

    async def get_user_by_login(self, login: str) -> TwitchUser: ...

    async def refresh_user_by_login(self, login: str) -> TwitchUser: ...

    async def get_user_by_id(self, user_id: str) -> TwitchUser: ...

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser: ...

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None: ...

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None: ...

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None: ...

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None: ...

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]: ...


class TwitchChannelLookup(Protocol):
    """Resolve broadcaster/channel metadata."""

    async def get_user_by_login(self, login: str) -> TwitchUser: ...

    async def refresh_channel_by_login(self, login: str) -> TwitchUser: ...

    async def get_channel_by_id(self, user_id: str) -> TwitchUser: ...


class TwitchDirectoryGateway(TwitchUserLookup, TwitchChannelLookup, Protocol):
    """Combined lookup contract for services that need both user and channel metadata."""

    pass


class TwitchAuthGateway(Protocol):
    """Run Twitch device-code and token workflows."""

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken: ...

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart: ...

    async def poll_device_code_flow(self, *, device_code: str, scopes: tuple[str, ...]) -> TwitchDevicePollResult: ...

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle: ...


class TwitchChatGateway(Protocol):
    """Send Twitch chat messages."""

    async def send_chat_message(
        self,
        *,
        access_token: str,
        client_id: str,
        sender_id: str,
        broadcaster_id: str,
        message: str,
        reply_parent_message_id: str | None = None,
    ) -> str: ...


class TwitchLiveGateway(Protocol):
    """Query live-state for broadcasters."""

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]: ...


class TwitchLiveMonitorGateway(TwitchLiveGateway, TwitchUserLookup, Protocol):
    """Combined live-state and user-resolution contract for the live monitor."""

    pass


class TwitchAccountGateway(TwitchAuthGateway, TwitchUserLookup, Protocol):
    """Combined contract used by account-link and device-flow services."""

    pass


class TwitchReplyGateway(TwitchChatGateway, TwitchAuthGateway, TwitchUserLookup, Protocol):
    """Combined Twitch contract used by reply execution services."""

    pass


class TwitchChannelStateLookup(TwitchChannelLookup, TwitchUserLookup, Protocol):
    """Combined lookup contract for channel-event configuration services."""

    pass


class TwitchIRCChannelGateway(Protocol):
    """Twitch IRC gateway methods consumed by services."""

    async def ensure_connected(self) -> None: ...

    async def join_channel(self, channel_login: str) -> None: ...

    async def leave_channel(self, channel_login: str) -> None: ...


class TwitchIRCConnectionGateway(TwitchIRCChannelGateway, Protocol):
    """Twitch IRC gateway methods needed by startup/runtime workers."""

    async def wait_until_connected(self) -> None: ...
