from __future__ import annotations

"""Slash-command registration for Discord context lifecycle commands."""

import logging
from contextlib import suppress

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordResultStyle

from ..dispatch import dispatch_thread_command
from ..helpers import command_unavailable_result, send_initial_result
from ..modals import LeaveConfirmationModal

logger = logging.getLogger(__name__)


def register_thread_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register Discord context lifecycle commands on the shared command tree."""

    @tree.command(name="join", description="Connect this Discord channel or DM to the observer.")
    async def join(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        logger.debug(
            "Discord join command discord_channel_id=%s requester_id=%s",
            interaction.channel_id,
            interaction.user.id,
        )
        result = await dispatch_thread_command(
            event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action="join",
        )
        await send_initial_result(interaction, result)
        if result.style == DiscordResultStyle.SUCCESS and isinstance(interaction.channel, discord.Thread):
            with suppress(discord.HTTPException, discord.Forbidden):
                await interaction.channel.join()

    @tree.command(name="leave", description="Disconnect this Discord channel or DM and delete its saved data.")
    async def leave(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        logger.debug(
            "Discord leave command discord_channel_id=%s requester_id=%s",
            interaction.channel_id,
            interaction.user.id,
        )
        await interaction.response.send_modal(
            LeaveConfirmationModal(
                event_bus=event_bus,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
            )
        )

    @tree.command(name="on", description="Enable tracking and auto-replies in this Discord channel.")
    async def on(interaction: discord.Interaction) -> None:
        await _handle_state_command(interaction, event_bus=event_bus, action="enable")

    @tree.command(name="off", description="Disable tracking and auto-replies in this Discord channel.")
    async def off(interaction: discord.Interaction) -> None:
        await _handle_state_command(interaction, event_bus=event_bus, action="disable")

    @tree.command(name="color", description="Set or clear the default Discord embed color for this observer context.")
    @discord.app_commands.describe(
        color="Optional color in #RRGGBB.",
        clear="Set to true to remove the stored observer color.",
    )
    async def color(interaction: discord.Interaction, color: str | None = None, clear: bool = False) -> None:
        await _handle_state_command(interaction, event_bus=event_bus, action="color", color=color, clear=clear)


async def _handle_state_command(
    interaction: discord.Interaction,
    *,
    event_bus: EventBus,
    action: str,
    color: str | None = None,
    clear: bool = False,
) -> None:
    """Handle `/on` and `/off` requests."""
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return

    logger.debug(
        "Discord observer state command discord_channel_id=%s requester_id=%s action=%s",
        interaction.channel_id,
        interaction.user.id,
        action,
    )
    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        action=action,
        color=color,
        clear_color=clear,
    )
    await send_initial_result(interaction, result)
