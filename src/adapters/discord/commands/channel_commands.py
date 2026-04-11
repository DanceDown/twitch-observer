from __future__ import annotations

"""Slash-command registration for tracked Twitch channel management."""

import logging

import discord
from discord import app_commands

from src.events.event_bus import EventBus

from ..dispatch import dispatch_channel_command
from ..helpers import command_unavailable_result, send_initial_result

logger = logging.getLogger(__name__)


def register_channel_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register the `/channel` command group on the shared command tree."""
    channel_group = app_commands.Group(name="channel", description="Manage tracked Twitch channels.")

    @channel_group.command(name="add", description="Track a Twitch channel in this Discord context.")
    @app_commands.describe(channel_name="The Twitch channel login to add.")
    async def channel_add(interaction: discord.Interaction, channel_name: str) -> None:
        await _handle_channel_command(interaction, event_bus=event_bus, action="add", channel_name=channel_name)

    @channel_group.command(name="remove", description="Stop tracking a Twitch channel in this Discord context.")
    @app_commands.describe(channel_name="The Twitch channel login to remove.")
    async def channel_remove(interaction: discord.Interaction, channel_name: str) -> None:
        await _handle_channel_command(interaction, event_bus=event_bus, action="remove", channel_name=channel_name)

    @channel_group.command(name="color", description="Set or clear the Discord embed color for one tracked Twitch channel.")
    @app_commands.describe(
        channel_name="The tracked Twitch channel login whose color should change.",
        color="Optional color in #RRGGBB.",
        clear="Set to true to remove the stored channel color.",
    )
    async def channel_color(
        interaction: discord.Interaction,
        channel_name: str,
        color: str | None = None,
        clear: bool = False,
    ) -> None:
        await _handle_channel_command(
            interaction,
            event_bus=event_bus,
            action="color",
            channel_name=channel_name,
            color=color,
            clear=clear,
        )

    tree.add_command(channel_group)


async def _handle_channel_command(
    interaction: discord.Interaction,
    *,
    event_bus: EventBus,
    action: str,
    channel_name: str,
    color: str | None = None,
    clear: bool = False,
) -> None:
    """Handle `/channel add/remove` requests."""
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return

    logger.debug(
        "Discord channel command discord_channel_id=%s requester_id=%s action=%s channel_name=%s",
        interaction.channel_id,
        interaction.user.id,
        action,
        channel_name,
    )
    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        action=action,
        twitch_channel_login=channel_name,
        color=color,
        clear_color=clear,
    )
    await send_initial_result(interaction, result)
