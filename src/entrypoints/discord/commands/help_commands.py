"""Slash-command registration for beginner-friendly help output."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.discord_results import DiscordResultStyle
from src.localization import Localizer
from src.services.help_service import HELP_SECTIONS

from ..dispatch import dispatch_help
from ..helpers import resolve_interaction_language, send_initial_result
from ..ui.show_ui import ShowPaginationView, build_show_pages
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text


def register_help_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/help` command."""
    _ = ui_data_provider

    section_choices = [
        discord.app_commands.Choice(name=command_text(localizer, f"help.choices.{section}"), value=section) for section in HELP_SECTIONS
    ]

    @tree.command(name="help", description=command_text(localizer, "help.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, section="help.options.section"))
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
