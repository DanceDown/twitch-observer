"""Slash-command registration for beginner-friendly help output."""

from __future__ import annotations

import discord

from src.events.discord_results import DiscordResultStyle
from src.localization import Localizer
from src.services.help_service import HELP_SECTIONS
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..dispatch import dispatch_help
from ..helpers import resolve_interaction_language, send_initial_result
from ..ui.show_ui import ShowPaginationView, build_show_pages
from ..ui_data import DiscordUIDataProvider


def register_help_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/help` command."""
    section_choices = [discord.app_commands.Choice(name=section, value=section) for section in HELP_SECTIONS]

    @tree.command(name="help", description="Explain how to use the bot.")
    @discord.app_commands.describe(section="Optional topic; leave empty for the general introduction.")
    @discord.app_commands.choices(section=section_choices)
    async def help_command(
        interaction: discord.Interaction,
        section: discord.app_commands.Choice[str] | None = None,
    ) -> None:
        result = await dispatch_help(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            language_hint=resolve_interaction_language(localizer, interaction),
            section=None if section is None else section.value,
        )
        if result.style != DiscordResultStyle.INFO or not result.ephemeral:
            await send_initial_result(interaction, result)
            return

        language = result.language or localizer.default_language
        pages = build_show_pages(
            result.message,
            empty_message="",
            item_prefix="- ",
        )
        if len(pages) <= 1:
            await send_initial_result(interaction, result)
            return

        view = ShowPaginationView(
            owner_id=interaction.user.id,
            result=result,
            localizer=localizer,
            language=language,
            item_prefix="- ",
        )
        await interaction.response.send_message(embed=view.render_embed(), view=view, ephemeral=True)
        view.bound_message = await interaction.original_response()
