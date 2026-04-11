from __future__ import annotations

"""Slash-command registration for per-thread permission management."""

import logging

import discord
from discord import app_commands

from src.events.event_bus import EventBus
from src.utils.permissions import PERMISSION_CHOICES

from ..dispatch import dispatch_permission_command
from ..helpers import command_unavailable_result, send_initial_result

logger = logging.getLogger(__name__)


def register_permission_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register the `/permission` command group on the shared command tree."""
    permission_group = app_commands.Group(name="permission", description="Manage per-user permissions in this Discord context.")

    @permission_group.command(name="grant", description="Grant one permission to a Discord user.")
    @app_commands.describe(user="The Discord user that should receive the permission.", permission="The permission to grant.")
    @app_commands.choices(
        permission=[app_commands.Choice(name=value, value=value) for value, _ in PERMISSION_CHOICES]
    )
    async def permission_grant(interaction: discord.Interaction, user: discord.User, permission: str) -> None:
        await _handle_permission_command(
            interaction,
            event_bus=event_bus,
            action="grant",
            target_user_id=user.id,
            permission=permission,
        )

    @permission_group.command(name="revoke", description="Revoke one permission from a Discord user.")
    @app_commands.describe(user="The Discord user that should lose the permission.", permission="The permission to revoke.")
    @app_commands.choices(
        permission=[app_commands.Choice(name=value, value=value) for value, _ in PERMISSION_CHOICES]
    )
    async def permission_revoke(interaction: discord.Interaction, user: discord.User, permission: str) -> None:
        await _handle_permission_command(
            interaction,
            event_bus=event_bus,
            action="revoke",
            target_user_id=user.id,
            permission=permission,
        )

    @permission_group.command(name="clear", description="Remove all explicitly granted permissions from a Discord user.")
    @app_commands.describe(user="The Discord user whose extra permissions should be removed.")
    async def permission_clear(interaction: discord.Interaction, user: discord.User) -> None:
        await _handle_permission_command(
            interaction,
            event_bus=event_bus,
            action="clear",
            target_user_id=user.id,
            permission=None,
        )

    tree.add_command(permission_group)


async def _handle_permission_command(
    interaction: discord.Interaction,
    *,
    event_bus: EventBus,
    action: str,
    target_user_id: int,
    permission: str | None,
) -> None:
    """Handle `/permission` grant/revoke/clear requests."""
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return

    logger.debug(
        "Discord permission command discord_channel_id=%s requester_id=%s action=%s target_user_id=%s permission=%s",
        interaction.channel_id,
        interaction.user.id,
        action,
        target_user_id,
        permission,
    )
    result = await dispatch_permission_command(
        event_bus,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        action=action,
        target_user_id=target_user_id,
        permission=permission,
    )
    await send_initial_result(interaction, result)
