"""Slash-command registration for Twitch account management."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_start_account_link, dispatch_unlink_account
from ..helpers import ensure_ui_flow_allowed, send_initial_result
from ..ui_data import DiscordUIDataProvider
from .localized import command_text


def register_account_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/account` action subcommands."""
    _ = ui_data_provider, localizer

    group = discord.app_commands.Group(name="account", description=command_text(localizer, "account.description"))

    @group.command(name="connect", description=command_text(localizer, "account.connect.description"))
    async def account_connect(interaction: discord.Interaction) -> None:
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.ACCOUNT, step=UIFlowStep.ROOT):
            return
        result = await dispatch_start_account_link(
            services,
            requester_id=interaction.user.id,
            discord_channel_id=interaction.channel_id,
        )
        await send_initial_result(interaction, result)

    @group.command(name="disconnect", description=command_text(localizer, "account.disconnect.description"))
    async def account_disconnect(interaction: discord.Interaction) -> None:
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.ACCOUNT, step=UIFlowStep.ROOT):
            return
        result = await dispatch_unlink_account(
            services,
            requester_id=interaction.user.id,
            discord_channel_id=interaction.channel_id,
        )
        await send_initial_result(interaction, result)

    tree.add_command(group)
