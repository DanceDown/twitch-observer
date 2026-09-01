"""Discord client implementation hosting slash commands and outbound messaging helpers."""

from __future__ import annotations

import logging

import discord

from src.config import AppConfig
from src.entrypoints.discord.delivery import DiscordEmbedSendRequest, send_embed_with_retries
from src.localization import Localizer
from src.utils.discord_embeds import build_result_embed

from .commands import (
    WriteCommandOptions,
    register_account_commands,
    register_channel_commands,
    register_help_commands,
    register_live_state_commands,
    register_pattern_commands,
    register_permission_commands,
    register_reply_commands,
    register_show_commands,
    register_support_commands,
    register_thread_commands,
    register_user_commands,
    register_write_commands,
)
from .commands.localized import CommandCatalogTranslator
from .service_bundle import DiscordServiceBundle
from .ui.support_ui import register_persistent_support_views
from .ui_data import DiscordUIDataProvider

logger = logging.getLogger(__name__)


class ObserverDiscordClient(discord.Client):
    """Discord client hosting the application's slash commands."""

    def __init__(
        self,
        config: AppConfig,
        services: DiscordServiceBundle,
        ui_data_provider: DiscordUIDataProvider,
        localizer: Localizer,
    ) -> None:
        """Create the Discord client and register its command tree holder."""
        intents = discord.Intents.default()
        if config.discord_application_id:
            super().__init__(intents=intents, application_id=config.discord_application_id)
        else:
            super().__init__(intents=intents)
        self._services = services
        self._ui_data_provider = ui_data_provider
        self._localizer = localizer
        self._config = config
        self.tree = discord.app_commands.CommandTree(self)
        self._guild_commands_cleaned = False

    async def setup_hook(self) -> None:
        """Register slash commands and sync them globally."""
        await self.tree.set_translator(CommandCatalogTranslator(self._localizer))
        register_thread_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_channel_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_live_state_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_user_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_pattern_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_permission_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_account_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_reply_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_help_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_write_commands(
            self.tree,
            self._services,
            self._ui_data_provider,
            self._localizer,
            WriteCommandOptions(
                reply_candidate_max_age_minutes=self._config.discord_write_reply_candidate_max_age_minutes,
                reply_candidate_limit=self._config.discord_write_reply_candidate_limit,
            ),
        )
        register_show_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        register_support_commands(self.tree, self._services, self._ui_data_provider, self._localizer)
        await register_persistent_support_views(client=self, services=self._services, localizer=self._localizer)
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
        thread_id: int | None = None,
    ) -> None:
        """Send a tracking embed to a Discord channel or DM."""
        _ = channel_login, thread_id
        channel = self.get_channel(discord_channel_id)
        messageable = (
            channel
            if isinstance(channel, discord.TextChannel | discord.Thread | discord.DMChannel)
            else self.get_partial_messageable(discord_channel_id)
        )
        await send_embed_with_retries(
            messageable,
            request=DiscordEmbedSendRequest(
                embed=embed,
                purpose="tracking embed",
                max_attempts=self._config.discord_delivery_max_attempts,
            ),
        )

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
        await send_embed_with_retries(
            channel,
            request=DiscordEmbedSendRequest(
                embed=build_result_embed(result),
                purpose="direct user result",
                max_attempts=self._config.discord_delivery_max_attempts,
            ),
        )

    async def send_channel_result(self, discord_channel_id: int, result) -> None:
        """Send a result embed to the originating Discord channel when possible."""
        channel = self.get_channel(discord_channel_id)
        if channel is None:
            channel = await self.fetch_channel(discord_channel_id)
        if isinstance(channel, discord.TextChannel | discord.Thread | discord.DMChannel):
            await send_embed_with_retries(
                channel,
                request=DiscordEmbedSendRequest(
                    embed=build_result_embed(result),
                    purpose="runtime channel result",
                    max_attempts=self._config.discord_delivery_max_attempts,
                ),
            )
