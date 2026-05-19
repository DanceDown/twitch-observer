"""Slash-command registration for tracked Twitch users."""

from __future__ import annotations

import discord

from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.shared import start_form
from ..ui.user_ui import UserMenuView
from ..ui_data import DiscordUIDataProvider


def register_user_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/user` command."""

    @tree.command(name="user", description="Add or remove tracked Twitch users.")
    async def user(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.USER, step=UIFlowStep.ROOT):
            return
        await start_form(
            interaction,
            view=UserMenuView(
                owner_id=interaction.user.id,
                services=services,
                data_provider=ui_data_provider,
                discord_channel_id=interaction.channel_id,
                localizer=localizer,
            ),
        )
