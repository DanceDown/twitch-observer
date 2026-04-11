from __future__ import annotations

"""Discord client implementation hosting slash commands and outbound messaging helpers."""

import logging

import discord

from src.config import AppConfig
from src.events.event_bus import EventBus
from src.utils.discord_embeds import build_result_embed

from .commands import (
    register_account_commands,
    register_channel_commands,
    register_permission_commands,
    register_pattern_commands,
    register_reply_commands,
    register_show_commands,
    register_thread_commands,
    register_write_commands,
)

logger = logging.getLogger(__name__)


class ObserverDiscordClient(discord.Client):
    """Discord client hosting the application's slash commands."""

    def __init__(self, config: AppConfig, event_bus: EventBus) -> None:
        intents = discord.Intents.default()
        if config.discord_application_id:
            super().__init__(intents=intents, application_id=config.discord_application_id)
        else:
            super().__init__(intents=intents)
        self._event_bus = event_bus
        self.tree = discord.app_commands.CommandTree(self)
        self._guild_commands_cleaned = False

    async def setup_hook(self) -> None:
        """Register slash commands and sync them globally."""
        register_thread_commands(self.tree, self._event_bus)
        register_channel_commands(self.tree, self._event_bus)
        register_pattern_commands(self.tree, self._event_bus)
        register_permission_commands(self.tree, self._event_bus)
        register_account_commands(self.tree, self._event_bus)
        register_reply_commands(self.tree, self._event_bus)
        register_write_commands(self.tree, self._event_bus)
        register_show_commands(self.tree, self._event_bus)
        await self.tree.sync()

    async def on_ready(self) -> None:
        """Remove stale guild-scoped command copies that previously caused duplicates."""
        if self._guild_commands_cleaned:
            return

        for guild in self.guilds:
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
        self._guild_commands_cleaned = True

    async def send_tracking_embed(self, discord_channel_id: int, embed: discord.Embed) -> None:
        """Send a tracking embed to a Discord channel or DM."""
        channel = self.get_channel(discord_channel_id)
        if channel is None:
            channel = await self.fetch_channel(discord_channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
            await channel.send(embed=embed)

    async def send_user_result(self, discord_user_id: int, result) -> None:
        """Send a result embed to a Discord user via DM when possible."""
        user = self.get_user(discord_user_id)
        if user is None:
            user = await self.fetch_user(discord_user_id)
        channel = user.dm_channel or await user.create_dm()
        await channel.send(embed=build_result_embed(result))

    async def send_channel_result(self, discord_channel_id: int, result) -> None:
        """Send a result embed to the originating Discord channel when possible."""
        channel = self.get_channel(discord_channel_id)
        if channel is None:
            channel = await self.fetch_channel(discord_channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
            await channel.send(embed=build_result_embed(result))
