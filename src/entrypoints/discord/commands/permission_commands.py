"""Slash-command registration for permission management."""

from __future__ import annotations

import discord

from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.permission_ui import PermissionMenuView
from ..ui.shared import start_form
from ..ui_data import DiscordUIDataProvider


def register_permission_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/permission` command."""

    @tree.command(name="permission", description="Grant, revoke, or clear the permissions of a Discord user.")
    async def permission(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.PERMISSION, step=UIFlowStep.ROOT):
            return
        await start_form(
            interaction,
            view=PermissionMenuView(
                owner_id=interaction.user.id,
                services=services,
                discord_channel_id=interaction.channel_id,
                data_provider=ui_data_provider,
                localizer=localizer,
            ),
        )
