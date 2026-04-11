from __future__ import annotations

"""Slash-command registration for manual Twitch chat sending."""

import logging

import discord
from discord import app_commands

from src.events.event_bus import EventBus

from ..dispatch import dispatch_write_command
from ..helpers import command_unavailable_result, normalize_optional_text, send_initial_result

logger = logging.getLogger(__name__)


def register_write_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register the direct `/write` command on the shared command tree."""

    @tree.command(name="write", description="Send one Twitch message, optionally as a reply to another Twitch message.")
    @app_commands.describe(
        channel_name="The tracked Twitch channel login that should receive the message.",
        message="The Twitch chat message to send.",
        reply_to_message_id="Optional Twitch message ID to reply to instead of sending a plain message.",
    )
    async def write(
        interaction: discord.Interaction,
        channel_name: str,
        message: str,
        reply_to_message_id: str | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        logger.debug(
            "Discord write command discord_channel_id=%s requester_id=%s channel_name=%s reply_to=%s",
            interaction.channel_id,
            interaction.user.id,
            channel_name,
            reply_to_message_id,
        )
        result = await dispatch_write_command(
            event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_login=channel_name,
            message=message,
            reply_parent_message_id=normalize_optional_text(reply_to_message_id),
        )
        await send_initial_result(interaction, result)
