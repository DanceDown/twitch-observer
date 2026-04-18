from __future__ import annotations

"""Slash-command registration for permission management."""

import discord

from src.events.event_bus import EventBus

from ..helpers import command_unavailable_result, send_initial_result
from ..ui.permission_ui import PermissionMenuView
from ..ui.shared import start_form


def register_permission_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register the single-word `/permission` command."""

    @tree.command(name="permission", description="Grant, revoke, or clear the permissions of a Discord user.")
    async def permission(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        await start_form(
            interaction,
            view=PermissionMenuView(
                owner_id=interaction.user.id,
                event_bus=event_bus,
                discord_channel_id=interaction.channel_id,
            ),
        )
