"""Bundle composed from the split Twitch services."""

from __future__ import annotations

from dataclasses import dataclass

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
        await self.directory.start()

    async def close(self) -> None:
        await self.directory.close()

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        return self.directory.get_cached_user_by_login(login)

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.directory.get_cached_user_by_id(user_id)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        return await self.directory.get_user_by_login(login)

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        return await self.directory.refresh_user_by_login(login)

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        return await self.directory.refresh_channel_by_login(login)

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        return await self.directory.get_user_by_id(user_id)

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        return await self.directory.get_channel_by_id(user_id)

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        return await self.directory.refresh_user_by_id(user_id)

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        return await self.auth.validate_user_access_token(access_token)

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart:
        return await self.auth.start_device_code_flow(scopes=scopes)

    async def poll_device_code_flow(
        self,
        *,
        device_code: str,
        scopes: tuple[str, ...],
    ) -> TwitchDevicePollResult:
        return await self.auth.poll_device_code_flow(device_code=device_code, scopes=scopes)

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle:
        return await self.auth.refresh_user_access_token(refresh_token)

    async def send_chat_message(
        self,
        *,
        access_token: str,
        client_id: str,
        sender_id: str,
        broadcaster_id: str,
        message: str,
        reply_parent_message_id: str | None = None,
    ) -> str:
        return await self.chat.send_chat_message(
            access_token=access_token,
            client_id=client_id,
            sender_id=sender_id,
            broadcaster_id=broadcaster_id,
            message=message,
            reply_parent_message_id=reply_parent_message_id,
        )

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        return await self.live.get_live_user_ids(user_ids)
