from __future__ import annotations

"""Slash-command registration for configuration overview commands."""

import logging

import discord
from discord import app_commands

from src.events.event_bus import EventBus

from ..dispatch import dispatch_show_command
from ..helpers import command_unavailable_result, send_initial_result

logger = logging.getLogger(__name__)


def register_show_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register `/show` on the shared command tree."""

    @tree.command(name="show", description="Show saved configuration for this Discord context.")
    @app_commands.describe(section="Which configuration section you want to inspect.")
    @app_commands.choices(
        section=[
            app_commands.Choice(name="channels", value="channels"),
            app_commands.Choice(name="pings", value="pings"),
            app_commands.Choice(name="auto_replies", value="auto_replies"),
            app_commands.Choice(name="permissions", value="permissions"),
        ]
    )
    async def show(interaction: discord.Interaction, section: str) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        logger.debug(
            "Discord show command discord_channel_id=%s requester_id=%s section=%s",
            interaction.channel_id,
            interaction.user.id,
            section,
        )
        result = await dispatch_show_command(
            event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            sections=(section,),
        )
        await send_initial_result(interaction, result)
