from __future__ import annotations

"""Slash-command registration for configuration overview."""

import discord

from src.events.event_bus import EventBus

from ..helpers import command_unavailable_result, send_initial_result
from ..ui.show_ui import ShowSectionModal


def register_show_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register the single-word `/show` command."""

    @tree.command(name="show", description="Show the settings of the current channel.")
    async def show(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        await interaction.response.send_modal(
            ShowSectionModal(
                event_bus=event_bus,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
            )
        )
