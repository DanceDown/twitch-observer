from __future__ import annotations

"""Slash-command registration for pattern-bound auto-replies."""

import logging

import discord
from discord import app_commands

from src.events.event_bus import EventBus

from ..dispatch import dispatch_reply_command
from ..helpers import command_unavailable_result, normalize_optional_text, send_initial_result

logger = logging.getLogger(__name__)


def register_reply_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register the `/reply` command group on the shared command tree."""
    reply_group = app_commands.Group(name="reply", description="Manage auto-replies attached to patterns.")

    @reply_group.command(name="add", description="Attach an auto-reply to a pattern.")
    @app_commands.describe(
        pattern_id="The stable pattern ID shown by /show.",
        message="The Twitch chat message to send when the pattern matches.",
        mode="Whether Twitch should send a normal chat message or a direct reply.",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="normal message", value="message"),
            app_commands.Choice(name="reply to the matched message", value="reply"),
        ]
    )
    async def reply_add(
        interaction: discord.Interaction,
        pattern_id: int,
        message: str,
        mode: str = "message",
    ) -> None:
        await _handle_reply_command(
            interaction,
            event_bus=event_bus,
            action="add",
            pattern_id=pattern_id,
            message=message,
            reply_as_reply=(mode == "reply"),
        )

    @reply_group.command(name="remove", description="Remove the auto-reply from a pattern.")
    @app_commands.describe(pattern_id="The stable pattern ID shown by /show.")
    async def reply_remove(interaction: discord.Interaction, pattern_id: int) -> None:
        await _handle_reply_command(
            interaction,
            event_bus=event_bus,
            action="remove",
            pattern_id=pattern_id,
            message=None,
            reply_as_reply=False,
        )

    @reply_group.command(name="disable", description="Disable the auto-reply on a pattern without deleting it.")
    @app_commands.describe(pattern_id="The stable pattern ID shown by /show.")
    async def reply_disable(interaction: discord.Interaction, pattern_id: int) -> None:
        await _handle_reply_command(
            interaction,
            event_bus=event_bus,
            action="disable",
            pattern_id=pattern_id,
            message=None,
            reply_as_reply=False,
        )

    @reply_group.command(name="enable", description="Enable the auto-reply on a pattern again.")
    @app_commands.describe(pattern_id="The stable pattern ID shown by /show.")
    async def reply_enable(interaction: discord.Interaction, pattern_id: int) -> None:
        await _handle_reply_command(
            interaction,
            event_bus=event_bus,
            action="enable",
            pattern_id=pattern_id,
            message=None,
            reply_as_reply=False,
        )

    tree.add_command(reply_group)


async def _handle_reply_command(
    interaction: discord.Interaction,
    *,
    event_bus: EventBus,
    action: str,
    pattern_id: int,
    message: str | None,
    reply_as_reply: bool,
) -> None:
    """Handle `/reply` add/remove/disable/enable requests."""
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return

    await interaction.response.defer(ephemeral=False)

    logger.debug(
        "Discord reply command discord_channel_id=%s requester_id=%s action=%s pattern_id=%s reply_as_reply=%s",
        interaction.channel_id,
        interaction.user.id,
        action,
        pattern_id,
        reply_as_reply,
    )
    result = await dispatch_reply_command(
        event_bus,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        action=action,
        pattern_id=pattern_id,
        message=normalize_optional_text(message),
        reply_as_reply=reply_as_reply,
    )
    await send_initial_result(interaction, result)
