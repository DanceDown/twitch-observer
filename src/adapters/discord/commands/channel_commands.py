from __future__ import annotations

"""Slash-command registration for tracked Twitch channels."""

import discord

from src.events.event_bus import EventBus
from src.localization import Localizer

from ..helpers import command_unavailable_result, send_initial_result
from ..ui.channel_ui import ChannelMenuView
from ..ui.shared import start_form
from ..ui_data import DiscordUIDataProvider


def register_channel_commands(
    tree: discord.app_commands.CommandTree,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/channel` command."""

    @tree.command(name="channel", description="Add, remove, or recolor tracked Twitch channels.")
    async def channel(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        await start_form(
            interaction,
            view=ChannelMenuView(
                owner_id=interaction.user.id,
                event_bus=event_bus,
                data_provider=ui_data_provider,
                discord_channel_id=interaction.channel_id,
                localizer=localizer,
            ),
        )
