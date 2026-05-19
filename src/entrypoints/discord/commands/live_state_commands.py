"""Slash-command registration for tracked Twitch live/offline notifications."""

from __future__ import annotations

import discord

from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.live_state_ui import open_live_state_menu
from ..ui_data import DiscordUIDataProvider


def register_live_state_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/live` as tracked event-notification management command."""

    @tree.command(name="live", description="Manage Twitch live and offline notifications for this Discord channel.")
    async def live(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.LIVE, step=UIFlowStep.ROOT):
            return
        await open_live_state_menu(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
        )
