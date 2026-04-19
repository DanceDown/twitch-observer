from __future__ import annotations

"""Slash-command registration for manual tracked-channel live/offline state changes."""

import discord

from src.events.event_bus import EventBus

from ..helpers import command_unavailable_result, send_initial_result
from ..ui.live_state_ui import open_channel_live_state_modal
from ..ui_data import DiscordUIDataProvider


def register_live_state_commands(
    tree: discord.app_commands.CommandTree,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
) -> None:
    """Register `/live` and `/offline` for manual tracked-channel state updates."""

    @tree.command(name="live", description="Mark one tracked Twitch channel as live.")
    async def live(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        await open_channel_live_state_modal(
            interaction,
            title="Mark Channel Live",
            event_bus=event_bus,
            ui_data_provider=ui_data_provider,
            is_live=True,
        )

    @tree.command(name="offline", description="Mark one tracked Twitch channel as offline.")
    async def offline(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        await open_channel_live_state_modal(
            interaction,
            title="Mark Channel Offline",
            event_bus=event_bus,
            ui_data_provider=ui_data_provider,
            is_live=False,
        )
