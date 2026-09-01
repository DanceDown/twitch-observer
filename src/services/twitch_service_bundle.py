"""Bundle composed from the split Twitch services."""

from __future__ import annotations

from dataclasses import dataclass

from src.events.twitch_events import TwitchChatSendRequest
from src.gateways.twitch_api import (
    TwitchDeviceCodeStart,
    TwitchDevicePollResult,
    TwitchUser,
    TwitchUserTokenBundle,
    TwitchValidatedToken,
)
from src.services.twitch_auth_service import TwitchAuthService
from src.services.twitch_chat_write_service import TwitchChatWriteService
from src.services.twitch_live_query_service import TwitchLiveQueryService
from src.services.twitch_user_directory_service import TwitchUserDirectoryService


@dataclass(slots=True)
class TwitchServiceBundle:
    """Expose the split Twitch responsibilities behind one shared surface."""

    directory: TwitchUserDirectoryService
    auth: TwitchAuthService
    chat: TwitchChatWriteService
    live: TwitchLiveQueryService

    async def start(self) -> None:
        """Start shared Twitch-side background resources."""
        await self.directory.start()

    async def close(self) -> None:
        """Close shared Twitch-side background resources."""
        await self.directory.close()

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        """Return an in-memory cached user by login without I/O."""
        return self.directory.get_cached_user_by_login(login)

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        """Return an in-memory cached user by ID without I/O."""
        return self.directory.get_cached_user_by_id(user_id)

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None:
        """Load a persisted cached user by login without upstream calls."""
        return await self.directory.load_cached_user_by_login(login)

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        """Load a persisted cached user by ID without upstream calls."""
        return await self.directory.load_cached_user_by_id(user_id)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        """Return a Twitch user by login through the directory service."""
        return await self.directory.get_user_by_login(login)

    async def get_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        """Return a Twitch user by login with Twitch chat-name color metadata."""
        return await self.directory.get_user_by_login_with_chat_color(login)

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        """Refresh a Twitch user by login through the directory service."""
        return await self.directory.refresh_user_by_login(login)

    async def refresh_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        """Refresh a Twitch user by login with Twitch chat-name color metadata."""
        return await self.directory.refresh_user_by_login_with_chat_color(login)

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        """Refresh broadcaster metadata by login through the directory service."""
        return await self.directory.refresh_channel_by_login(login)

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        """Return a Twitch user by ID through the directory service."""
        return await self.directory.get_user_by_id(user_id)

    async def get_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        """Return a Twitch user by ID with Twitch chat-name color metadata."""
        return await self.directory.get_user_by_id_with_chat_color(user_id)

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        """Return broadcaster metadata by Twitch user ID."""
        return await self.directory.get_channel_by_id(user_id)

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        """Refresh a Twitch user by ID through the directory service."""
        return await self.directory.refresh_user_by_id(user_id)

    async def refresh_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        """Refresh a Twitch user by ID with Twitch chat-name color metadata."""
        return await self.directory.refresh_user_by_id_with_chat_color(user_id)

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        """Return many Twitch users by ID through the directory service."""
        return await self.directory.get_users_by_ids(user_ids)

    async def get_users_by_ids_with_chat_colors(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        """Return many Twitch users by ID with Twitch chat-name color metadata."""
        return await self.directory.get_users_by_ids_with_chat_colors(user_ids)

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        """Validate a Twitch user access token through the auth service."""
        return await self.auth.validate_user_access_token(access_token)

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart:
        """Start a Twitch device-code login flow through the auth service."""
        return await self.auth.start_device_code_flow(scopes=scopes)

    async def poll_device_code_flow(
        self,
        *,
        device_code: str,
        scopes: tuple[str, ...],
    ) -> TwitchDevicePollResult:
        """Poll a Twitch device-code login flow through the auth service."""
        return await self.auth.poll_device_code_flow(device_code=device_code, scopes=scopes)

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle:
        """Refresh a Twitch user access token through the auth service."""
        return await self.auth.refresh_user_access_token(refresh_token)

    async def send_chat_message(self, request: TwitchChatSendRequest) -> str:
        """Send one Twitch chat message through the chat service."""
        return await self.chat.send_chat_message(request)

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        """Return currently live Twitch user IDs through the live query service."""
        return await self.live.get_live_user_ids(user_ids)
