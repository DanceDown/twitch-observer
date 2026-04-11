from __future__ import annotations

"""Lifecycle wrapper around the Discord client implementation."""

from contextlib import suppress

import discord

from src.config import AppConfig
from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult
from src.services.pattern_service import TrackingNotificationSender

from .client import ObserverDiscordClient


class DiscordAdapter(TrackingNotificationSender):
    """Wrapper managing the Discord client lifecycle."""

    def __init__(self, config: AppConfig, event_bus: EventBus) -> None:
        self._config = config
        self._client = ObserverDiscordClient(config=config, event_bus=event_bus)

    async def start(self) -> None:
        """Connect the Discord bot if a token is configured."""
        if not self._config.discord_bot_token:
            print("No Discord bot token configured; Discord adapter is disabled.")
            return
        await self._client.start(self._config.discord_bot_token)

    async def stop(self) -> None:
        """Close the Discord client."""
        if not self._client.is_closed():
            await self._client.close()

    async def send_tracking_embed(self, discord_channel_id: int, embed: discord.Embed) -> None:
        """Send a tracking embed through the Discord client."""
        if not self._config.discord_bot_token or not self._client.is_ready():
            return
        with suppress(discord.HTTPException):
            await self._client.send_tracking_embed(discord_channel_id, embed)

    async def send_account_result(
        self,
        discord_user_id: int,
        discord_channel_id: int | None,
        result: DiscordCommandResult,
    ) -> None:
        """Send a Twitch account status update to the originating channel, with DM fallback."""
        if not self._config.discord_bot_token or not self._client.is_ready():
            return
        if discord_channel_id is not None:
            with suppress(discord.HTTPException, discord.Forbidden):
                await self._client.send_channel_result(discord_channel_id, result)
                return
        with suppress(discord.HTTPException, discord.Forbidden):
            await self._client.send_user_result(discord_user_id, result)
