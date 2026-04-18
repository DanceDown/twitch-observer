from __future__ import annotations

"""Slash-command registration for manual Twitch writing."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle

from ..helpers import command_unavailable_result, send_initial_result
from ..ui.write_ui import WriteModal
from ..ui_data import DiscordUIDataProvider


def register_write_commands(
    tree: discord.app_commands.CommandTree,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
) -> None:
    """Register the single-word `/write` command."""

    @tree.command(name="write", description="Send a Twitch message from the linked account.")
    async def write(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
        if not tracked_channels:
            await send_initial_result(
                interaction,
                DiscordCommandResult(
                    title="No Tracked Channels",
                    message="Track a Twitch channel first before sending messages.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(
            WriteModal(
                event_bus=event_bus,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                tracked_channels=tracked_channels,
            )
        )
