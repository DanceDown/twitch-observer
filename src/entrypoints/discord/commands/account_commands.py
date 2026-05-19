"""Slash-command registration for Twitch account management."""

from __future__ import annotations

import discord

from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..helpers import ensure_ui_flow_allowed
from ..ui.account_ui import AccountMenuView
from ..ui.shared import start_form
from ..ui_data import DiscordUIDataProvider


def register_account_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/account` command."""

    @tree.command(name="account", description="Connect or disconnect your Twitch account.")
    async def account(interaction: discord.Interaction) -> None:
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.ACCOUNT, step=UIFlowStep.ROOT):
            return
        await start_form(
            interaction,
            view=AccountMenuView(
                owner_id=interaction.user.id,
                services=services,
                discord_channel_id=interaction.channel_id,
                data_provider=ui_data_provider,
                localizer=localizer,
            ),
        )
