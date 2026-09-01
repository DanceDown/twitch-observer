"""Slash-command registration for configuration overview."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.discord_results import DiscordResultStyle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_show_configuration
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.show_ui import ShowPaginationView, ShowSectionModal, _show_section_item_prefix
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text


def register_show_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/show` command."""
    section_choices = [
        discord.app_commands.Choice(name=command_text(localizer, "show.choices.pings"), value="pings"),
        discord.app_commands.Choice(name=command_text(localizer, "show.choices.auto_replies"), value="auto_replies"),
        discord.app_commands.Choice(name=command_text(localizer, "show.choices.stream_pings"), value="stream_pings"),
        discord.app_commands.Choice(name=command_text(localizer, "show.choices.channels"), value="channels"),
        discord.app_commands.Choice(name=command_text(localizer, "show.choices.users"), value="users"),
        discord.app_commands.Choice(name=command_text(localizer, "show.choices.permissions"), value="permissions"),
        discord.app_commands.Choice(name=command_text(localizer, "show.choices.account"), value="account"),
    ]

    @tree.command(name="show", description=command_text(localizer, "show.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, section="show.options.section"))
    @discord.app_commands.choices(section=section_choices)
    async def show(
        interaction: discord.Interaction,
        section: discord.app_commands.Choice[str] | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.SHOW, step=UIFlowStep.ROOT):
            return
        if section is not None:
            result = await dispatch_show_configuration(
                services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                sections=(section.value,),
            )
            if result.style != DiscordResultStyle.INFO or not result.ephemeral:
                await send_initial_result(interaction, result)
                return
            language = await ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language
            view = ShowPaginationView(
                owner_id=interaction.user.id,
                result=result,
                localizer=localizer,
                language=language,
                item_prefix=_show_section_item_prefix(
                    localizer=localizer,
                    language=language,
                    section=section.value,
                ),
            )
            await interaction.response.send_message(embed=view.render_embed(), view=view, ephemeral=True)
            view.bound_message = await interaction.original_response()
            return
        await interaction.response.send_modal(
            ShowSectionModal(
                language=await ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language,
                services=services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                localizer=localizer,
            )
        )
