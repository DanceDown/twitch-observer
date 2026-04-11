from __future__ import annotations

"""Slash-command registration for Twitch account linking commands."""

import logging

import discord
from discord import app_commands

from src.events.event_bus import EventBus

from ..dispatch import dispatch_account_command
from ..helpers import send_initial_result

logger = logging.getLogger(__name__)


def register_account_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register the `/account` command group on the shared command tree."""
    account_group = app_commands.Group(name="account", description="Manage the Twitch account linked to this Discord channel.")

    @account_group.command(name="link", description="Start the Twitch device login flow for this Discord channel.")
    async def account_link(interaction: discord.Interaction) -> None:
        await _handle_account_command(interaction, event_bus=event_bus, action="link")

    @account_group.command(name="unlink", description="Remove the Twitch account linked to this Discord channel.")
    async def account_unlink(interaction: discord.Interaction) -> None:
        await _handle_account_command(interaction, event_bus=event_bus, action="unlink")

    @account_group.command(name="show", description="Show the Twitch account linked to this Discord channel.")
    async def account_show(interaction: discord.Interaction) -> None:
        await _handle_account_command(interaction, event_bus=event_bus, action="show")

    tree.add_command(account_group)


async def _handle_account_command(
    interaction: discord.Interaction,
    *,
    event_bus: EventBus,
    action: str,
) -> None:
    """Handle `/account` commands."""
    logger.debug("Discord account command requester_id=%s action=%s", interaction.user.id, action)
    result = await dispatch_account_command(
        event_bus,
        requester_id=interaction.user.id,
        discord_channel_id=interaction.channel_id,
        action=action,
    )
    await send_initial_result(interaction, result)
