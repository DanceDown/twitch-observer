"""Lifecycle wrapper around the Discord client implementation."""

from __future__ import annotations

import logging
from contextlib import suppress

import aiohttp
import discord

from src.config import AppConfig
from src.events.discord_results import DiscordCommandResult
from src.localization import Localizer
from src.services.discord_presence_service import DiscordPresenceStatusSender
from src.services.patterns import TrackingNotificationSender

from .client import ObserverDiscordClient
from .service_bundle import DiscordServiceBundle
from .ui_data import DiscordUIDataProvider

logger = logging.getLogger(__name__)


class DiscordEntrypoint(TrackingNotificationSender, DiscordPresenceStatusSender):
    """Entrypoint managing the Discord client lifecycle."""

    def __init__(
        self,
        config: AppConfig,
        services: DiscordServiceBundle,
        *,
        ui_data_provider: DiscordUIDataProvider,
        localizer: Localizer,
    ) -> None:
        """Create the entrypoint wrapper around the concrete Discord client."""
        self._config = config
        self._client = ObserverDiscordClient(
            config=config,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
        )

    async def start(self) -> None:
        """Connect the Discord bot if a token is configured."""
        if not self._config.discord_bot_token:
            logger.info("No Discord bot token configured; the Discord entrypoint is disabled.")
            return
        await self._client.start(self._config.discord_bot_token)

    async def stop(self) -> None:
        """Close the Discord client."""
        if not self._client.is_closed():
            await self._client.close()

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        """Send a tracking embed through the Discord client."""
        _ = thread_id
        if not self._config.discord_bot_token or not self._client.is_ready():
            return
        with suppress(discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
            await self._client.send_tracking_embed(discord_channel_id, embed, channel_login=channel_login)

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

    async def send_channel_result(self, discord_channel_id: int, result: DiscordCommandResult) -> None:
        """Send a result embed to one Discord channel when possible."""
        if not self._config.discord_bot_token or not self._client.is_ready():
            return
        with suppress(discord.HTTPException, discord.Forbidden):
            await self._client.send_channel_result(discord_channel_id, result)

    async def set_status_text(self, text: str) -> None:
        """Update the bot's visible global Discord custom status."""
        if not self._config.discord_bot_token or not self._client.is_ready():
            return
        with suppress(discord.HTTPException, discord.ConnectionClosed, aiohttp.ClientConnectionError):
            await self._client.set_status_text(text)
