from __future__ import annotations

"""Discord client implementation hosting slash commands and outbound messaging helpers."""

import logging

import discord

from src.config import AppConfig
from src.events.event_bus import EventBus
from src.localization import Localizer
from src.utils.discord_embeds import build_result_embed, build_tracking_view

from .commands import (
    register_account_commands,
    register_channel_commands,
    register_live_state_commands,
    register_permission_commands,
    register_pattern_commands,
    register_reply_commands,
    register_show_commands,
    register_thread_commands,
    register_user_commands,
    register_write_commands,
)
from .ui_data import DiscordUIDataProvider

logger = logging.getLogger(__name__)


class ObserverDiscordClient(discord.Client):
    """Discord client hosting the application's slash commands."""

    def __init__(
        self,
        config: AppConfig,
        event_bus: EventBus,
        ui_data_provider: DiscordUIDataProvider,
        localizer: Localizer,
    ) -> None:
        intents = discord.Intents.default()
        if config.discord_application_id:
            super().__init__(intents=intents, application_id=config.discord_application_id)
        else:
            super().__init__(intents=intents)
        self._event_bus = event_bus
        self._ui_data_provider = ui_data_provider
        self._localizer = localizer
        self.tree = discord.app_commands.CommandTree(self)
        self._guild_commands_cleaned = False

    async def setup_hook(self) -> None:
        """Register slash commands and sync them globally."""
        register_thread_commands(self.tree, self._event_bus, self._ui_data_provider, self._localizer)
        register_channel_commands(self.tree, self._event_bus, self._ui_data_provider)
        register_live_state_commands(self.tree, self._event_bus, self._ui_data_provider)
        register_user_commands(self.tree, self._event_bus, self._ui_data_provider)
        register_pattern_commands(self.tree, self._event_bus, self._ui_data_provider)
        register_permission_commands(self.tree, self._event_bus)
        register_account_commands(self.tree, self._event_bus)
        register_reply_commands(self.tree, self._event_bus, self._ui_data_provider)
        register_write_commands(self.tree, self._event_bus, self._ui_data_provider)
        register_show_commands(self.tree, self._event_bus)
        await self.tree.sync()
        logger.info("Synced global Discord commands: %s", ", ".join(command.name for command in self.tree.get_commands()))

    async def on_ready(self) -> None:
        """Remove stale guild-scoped command copies that previously caused duplicates."""
        if self._guild_commands_cleaned:
            return

        for guild in self.guilds:
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
        self._guild_commands_cleaned = True

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
    ) -> None:
        """Send a tracking embed to a Discord channel or DM."""
        channel = self.get_channel(discord_channel_id)
        if channel is None:
            channel = await self.fetch_channel(discord_channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
            thread = self._ui_data_provider.get_thread(discord_channel_id)
            language = self._localizer.language_for_thread(thread)
            view = (
                None
                if channel_login is None
                else build_tracking_view(
                    channel_login=channel_login,
                    localizer=self._localizer,
                    language=language,
                )
            )
            await channel.send(embed=embed, view=view)

    async def set_status_text(self, text: str) -> None:
        """Update the bot's global Discord custom status text."""
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.CustomActivity(name=text),
        )

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
