"""Slash-command registration for Discord context lifecycle commands."""

from __future__ import annotations

import logging
from contextlib import suppress

import discord
from discord import ChannelType

from src.discord_results import build_result
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import (
    dispatch_disable_thread,
    dispatch_enable_thread,
    dispatch_join_thread,
    dispatch_set_thread_language,
)
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.thread_ui import LeaveConfirmationModal, ThreadColorModal
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text

logger = logging.getLogger(__name__)


def register_thread_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register Discord context lifecycle commands on the shared command tree."""

    @tree.command(name="join", description=command_text(localizer, "thread.join.description"))
    async def join(interaction: discord.Interaction) -> None:
        await _handle_join_command(interaction, services=services, localizer=localizer)

    @tree.command(name="leave", description=command_text(localizer, "thread.leave.description"))
    async def leave(interaction: discord.Interaction) -> None:
        await _handle_leave_command(interaction, services=services, ui_data_provider=ui_data_provider, localizer=localizer)

    @tree.command(name="on", description=command_text(localizer, "thread.on.description"))
    async def on(interaction: discord.Interaction) -> None:
        await _handle_state_command(interaction, services=services, action="enable")

    @tree.command(name="off", description=command_text(localizer, "thread.off.description"))
    async def off(interaction: discord.Interaction) -> None:
        await _handle_state_command(interaction, services=services, action="disable")

    @tree.command(name="color", description=command_text(localizer, "thread.color.description"))
    async def color(interaction: discord.Interaction) -> None:
        await _handle_color_command(interaction, services=services, ui_data_provider=ui_data_provider, localizer=localizer)

    @tree.command(name="language", description=command_text(localizer, "thread.language.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, language="thread.language.options.language"))
    @discord.app_commands.choices(
        language=[
            discord.app_commands.Choice(name=command_text(localizer, "thread.language.choices.english"), value="english"),
            discord.app_commands.Choice(name=command_text(localizer, "thread.language.choices.german"), value="german"),
        ]
    )
    async def language(
        interaction: discord.Interaction,
        language: discord.app_commands.Choice[str],
    ) -> None:
        await _handle_language_command(interaction, services=services, language=language.value)


async def _handle_join_command(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    localizer: Localizer,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await _ensure_thread_membership_for_join(interaction, localizer):
        return
    if not _can_send_public_result(interaction):
        await send_initial_result(interaction, _missing_channel_access_result(localizer, interaction))
        return

    logger.debug(
        "Discord join command discord_channel_id=%s requester_id=%s",
        interaction.channel_id,
        interaction.user.id,
    )
    result = await dispatch_join_thread(
        services,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
    )
    await send_initial_result(interaction, result)
    if result.style == DiscordResultStyle.SUCCESS and isinstance(interaction.channel, discord.Thread):
        with suppress(discord.HTTPException, discord.Forbidden):
            await interaction.channel.join()


async def _handle_leave_command(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.THREAD, step=UIFlowStep.LEAVE):
        return

    logger.debug(
        "Discord leave command discord_channel_id=%s requester_id=%s",
        interaction.channel_id,
        interaction.user.id,
    )
    await interaction.response.send_modal(
        LeaveConfirmationModal(
            language=await ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language,
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            localizer=localizer,
        )
    )


async def _handle_color_command(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.THREAD, step=UIFlowStep.COLOR):
        return
    await interaction.response.send_modal(
        ThreadColorModal(
            language=await ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language,
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            localizer=localizer,
        ),
    )


async def _handle_language_command(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    language: str,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    result = await dispatch_set_thread_language(
        services,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        language=language,
    )
    await send_initial_result(interaction, result)


async def _handle_state_command(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    action: str,
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
    if action == "enable":
        result = await dispatch_enable_thread(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
        )
    else:
        result = await dispatch_disable_thread(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
        )
    await send_initial_result(interaction, result)


def _can_send_public_result(interaction: discord.Interaction) -> bool:
    """Return whether the bot can post a public embed in the interaction context."""
    if interaction.guild is None:
        return True
    permissions = interaction.app_permissions
    if permissions is None:
        return True
    if not permissions.view_channel or not permissions.embed_links:
        return False
    thread_channel_types = {ChannelType.public_thread, ChannelType.private_thread, ChannelType.news_thread}
    channel_type = interaction.channel.type if interaction.channel is not None else None
    if channel_type in thread_channel_types:
        return permissions.send_messages_in_threads
    return permissions.send_messages


def _missing_channel_access_result(localizer: Localizer, interaction: discord.Interaction) -> DiscordCommandResult:
    """Build the localized ephemeral result used when the bot cannot post in the target channel."""
    language = _interaction_language(localizer, interaction)
    return build_result(
        localizer,
        "results.thread.missing_channel_access",
        language=language,
        style=DiscordResultStyle.ERROR,
        ephemeral=True,
    )


def _interaction_language(localizer: Localizer, interaction: discord.Interaction) -> str:
    """Best-effort language selection before a thread-specific language exists."""
    locale_value = str(interaction.locale).lower()
    if locale_value.startswith("de"):
        return "german"
    if locale_value.startswith("en"):
        return "english"
    return localizer.default_language


async def _ensure_thread_membership_for_join(interaction: discord.Interaction, localizer: Localizer) -> bool:
    """Ensure the bot can join thread contexts before creating any persisted thread state."""
    channel = interaction.channel
    if channel is None:
        await send_initial_result(interaction, command_unavailable_result())
        return False
    thread_channel_types = {ChannelType.public_thread, ChannelType.private_thread, ChannelType.news_thread}
    if channel.type not in thread_channel_types:
        return True

    thread: discord.Thread | None = channel if isinstance(channel, discord.Thread) else None
    if thread is None:
        try:
            fetched_channel = await interaction.client.fetch_channel(interaction.channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            await send_initial_result(interaction, _missing_channel_access_result(localizer, interaction))
            return False
        if not isinstance(fetched_channel, discord.Thread):
            await send_initial_result(interaction, _missing_channel_access_result(localizer, interaction))
            return False
        thread = fetched_channel

    try:
        await thread.join()
    except (discord.Forbidden, discord.HTTPException):
        await send_initial_result(interaction, _missing_channel_access_result(localizer, interaction))
        return False
    return True
