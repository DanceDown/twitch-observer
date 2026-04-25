from __future__ import annotations

"""Slash-command registration for Discord context lifecycle commands."""

import logging
from contextlib import suppress

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordResultStyle
from src.localization import Localizer

from ..dispatch import dispatch_thread_command
from ..helpers import command_unavailable_result, send_initial_result
from ..ui.thread_ui import LeaveConfirmationModal, ThreadColorModal
from ..ui_data import DiscordUIDataProvider

logger = logging.getLogger(__name__)


def register_thread_commands(
    tree: discord.app_commands.CommandTree,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register Discord context lifecycle commands on the shared command tree."""

    @tree.command(name="join", description="Let the Twitch Observer join this Discord channel.")
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

    @tree.command(name="leave", description="Remove the Twitch Observer from this Discord channel and delete all data.")
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
                data_provider=ui_data_provider,
                localizer=localizer,
            )
        )

    @tree.command(name="on", description="Enable the Twitch Observer.")
    async def on(interaction: discord.Interaction) -> None:
        await _handle_state_command(interaction, event_bus=event_bus, action="enable")

    @tree.command(name="off", description="Disable the Twitch Observer.")
    async def off(interaction: discord.Interaction) -> None:
        await _handle_state_command(interaction, event_bus=event_bus, action="disable")

    @tree.command(name="color", description="Set the default Discord color for messages.")
    async def color(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        await interaction.response.send_modal(
            ThreadColorModal(
                event_bus=event_bus,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                data_provider=ui_data_provider,
                localizer=localizer,
            ),
        )

    @tree.command(name="language", description="Set the language for this Discord channel.")
    @discord.app_commands.describe(language="Language used for this Discord channel.")
    @discord.app_commands.choices(
        language=[
            discord.app_commands.Choice(name="english", value="english"),
            discord.app_commands.Choice(name="german", value="german"),
        ]
    )
    async def language(
        interaction: discord.Interaction,
        language: discord.app_commands.Choice[str],
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        result = await dispatch_thread_command(
            event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action="language",
            language=language.value,
        )
        await send_initial_result(interaction, result)


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
