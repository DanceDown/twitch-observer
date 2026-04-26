from __future__ import annotations

"""Slash-command registration for tracked Twitch live/offline notifications."""

import discord

from src.events.event_bus import EventBus
from src.localization import Localizer

from ..helpers import command_unavailable_result, send_initial_result
from ..ui.live_state_ui import open_channel_event_modal
from ..ui_data import DiscordUIDataProvider


def register_live_state_commands(
    tree: discord.app_commands.CommandTree,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/live` and `/offline` as tracked event-notification commands."""

    @tree.command(name="live", description="Notify this Discord channel when a tracked Twitch channel goes live.")
    async def live(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        await open_channel_event_modal(
            interaction,
            event_bus=event_bus,
            ui_data_provider=ui_data_provider,
            event_key="stream.online",
            localizer=localizer,
        )

    @tree.command(name="offline", description="Notify this Discord channel when a tracked Twitch channel goes offline.")
    async def offline(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        await open_channel_event_modal(
            interaction,
            event_bus=event_bus,
            ui_data_provider=ui_data_provider,
            event_key="stream.offline",
            localizer=localizer,
        )
