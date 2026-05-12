"""Slash-command registration for configuration overview."""

from __future__ import annotations

import discord

from src.events.event_bus import EventBus
from src.localization import Localizer

from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.show_ui import ShowSectionModal
from ..ui_data import DiscordUIDataProvider


def register_show_commands(
    tree: discord.app_commands.CommandTree,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/show` command."""

    @tree.command(name="show", description="Show the settings of the current channel.")
    async def show(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, event_bus, flow="show", step="root"):
            return
        await interaction.response.send_modal(
            ShowSectionModal(
                event_bus=event_bus,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
            )
        )
