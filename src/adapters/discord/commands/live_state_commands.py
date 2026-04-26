"""Slash-command registration for tracked Twitch live/offline notifications."""

from __future__ import annotations

import discord

from src.events.event_bus import EventBus
from src.localization import Localizer

from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.live_state_ui import open_live_state_menu
from ..ui_data import DiscordUIDataProvider


def register_live_state_commands(
    tree: discord.app_commands.CommandTree,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/live` as tracked event-notification management command."""

    @tree.command(name="live", description="Manage Twitch live and offline notifications for this Discord channel.")
    async def live(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, event_bus, flow="live", step="root"):
            return
        await open_live_state_menu(
            interaction,
            event_bus=event_bus,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
        )
