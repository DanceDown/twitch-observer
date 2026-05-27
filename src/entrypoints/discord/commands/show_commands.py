"""Slash-command registration for configuration overview."""

from __future__ import annotations

import discord

from src.events.event_types import DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..dispatch import dispatch_show_configuration
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.show_ui import ShowPaginationView, ShowSectionModal
from ..ui_data import DiscordUIDataProvider


def register_show_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/show` command."""

    section_choices = [
        discord.app_commands.Choice(name="pings", value="pings"),
        discord.app_commands.Choice(name="auto_replies", value="auto_replies"),
        discord.app_commands.Choice(name="channels", value="channels"),
        discord.app_commands.Choice(name="users", value="users"),
        discord.app_commands.Choice(name="permissions", value="permissions"),
        discord.app_commands.Choice(name="account", value="account"),
    ]

    @tree.command(name="show", description="Show the settings of the current channel.")
    @discord.app_commands.describe(section="Optional section; leave empty to pick from the modal.")
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
            language = ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language
            view = ShowPaginationView(
                owner_id=interaction.user.id,
                result=result,
                localizer=localizer,
                language=language,
            )
            await interaction.response.send_message(embed=view.render_embed(), view=view, ephemeral=True)
            view.bound_message = await interaction.original_response()
            return
        await interaction.response.send_modal(
            ShowSectionModal(
                services=services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
            )
        )
