"""Twitch auth workflows split from user-directory lookup responsibilities."""

from __future__ import annotations

from dataclasses import dataclass

from src.gateways.twitch_api import (
    TwitchAPIClient,
    TwitchDeviceCodeStart,
    TwitchDevicePollResult,
    TwitchUserTokenBundle,
    TwitchValidatedToken,
)


@dataclass(slots=True)
class TwitchAuthService:
    """Run Twitch device-code and user-token workflows."""

    twitch_api: TwitchAPIClient

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        """Validate a Twitch user access token through Helix."""
        return await self.twitch_api.validate_user_access_token(access_token)

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart:
        """Start a Twitch Device Code Flow for the requested scopes."""
        return await self.twitch_api.start_device_code_flow(scopes=scopes)

    async def poll_device_code_flow(
        self,
        *,
        device_code: str,
        scopes: tuple[str, ...],
    ) -> TwitchDevicePollResult:
        """Poll Twitch for the current Device Code Flow status."""
        return await self.twitch_api.poll_device_code_flow(device_code=device_code, scopes=scopes)

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle:
        """Refresh a Twitch user access token with the stored refresh token."""
        return await self.twitch_api.refresh_user_access_token(refresh_token)
