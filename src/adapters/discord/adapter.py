from __future__ import annotations

"""Lifecycle wrapper around the Discord client implementation."""

from contextlib import suppress

import discord

from src.config import AppConfig
from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRepository,
)
from src.database.connection import TrackedUserRepository
from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult
from src.localization import Localizer
from src.services.discord_presence_service import DiscordPresenceStatusSender
from src.services.pattern_service import TrackingNotificationSender
from src.adapters.twitch_api import TwitchAPIClient

from .client import ObserverDiscordClient
from .ui_data import DiscordUIDataProvider


class DiscordAdapter(TrackingNotificationSender, DiscordPresenceStatusSender):
    """Wrapper managing the Discord client lifecycle."""

    def __init__(
        self,
        config: AppConfig,
        event_bus: EventBus,
        *,
        thread_repository: ThreadRepository,
        channel_repository: ChannelRepository,
        tracked_user_repository: TrackedUserRepository,
        pattern_repository: PatternRepository,
        reply_repository: ReplyRepository,
        adapter_event_repository: AdapterEventRepository,
        adapter_event_action_repository: AdapterEventActionRepository,
        twitch_api: TwitchAPIClient,
        localizer: Localizer,
    ) -> None:
        self._config = config
        self._client = ObserverDiscordClient(
            config=config,
            event_bus=event_bus,
            ui_data_provider=DiscordUIDataProvider(
                thread_repository=thread_repository,
                channel_repository=channel_repository,
                tracked_user_repository=tracked_user_repository,
                pattern_repository=pattern_repository,
                reply_repository=reply_repository,
                adapter_event_repository=adapter_event_repository,
                adapter_event_action_repository=adapter_event_action_repository,
                twitch_api=twitch_api,
            ),
            localizer=localizer,
        )

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

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
    ) -> None:
        """Send a tracking embed through the Discord client."""
        if not self._config.discord_bot_token or not self._client.is_ready():
            return
        with suppress(discord.HTTPException):
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
        with suppress(discord.HTTPException):
            await self._client.set_status_text(text)
