"""Slash-command registration for tracked Twitch channels."""

from __future__ import annotations

from dataclasses import dataclass

import discord

from src.discord_results import build_result
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.discord_results import DiscordResultStyle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_add_tracked_channel, dispatch_remove_tracked_channel, dispatch_set_tracked_channel_color
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.channel_ui import ChannelNameModal, ChannelSelectionModal
from ..ui.shared import DiscordModalContext
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text


@dataclass(slots=True, frozen=True)
class _ChannelCommandContext:
    services: DiscordServiceBundle
    ui_data_provider: DiscordUIDataProvider
    localizer: Localizer


def register_channel_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/channel` action subcommands."""
    group = discord.app_commands.Group(name="channel", description=command_text(localizer, "channel.description"))
    context = _ChannelCommandContext(services=services, ui_data_provider=ui_data_provider, localizer=localizer)

    @group.command(name="add", description=command_text(localizer, "channel.add.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, twitch_channel_login="channel.add.options.twitch_channel_login"))
    async def channel_add(interaction: discord.Interaction, twitch_channel_login: str | None = None) -> None:
        await _handle_channel_add(
            interaction,
            twitch_channel_login=twitch_channel_login,
            context=context,
        )

    @group.command(name="remove", description=command_text(localizer, "channel.remove.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, twitch_channel_login="channel.remove.options.twitch_channel_login"))
    async def channel_remove(interaction: discord.Interaction, twitch_channel_login: str | None = None) -> None:
        await _handle_channel_remove(
            interaction,
            twitch_channel_login=twitch_channel_login,
            context=context,
        )

    @group.command(name="color", description=command_text(localizer, "channel.color.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            twitch_channel_login="channel.color.options.twitch_channel_login",
            color="channel.color.options.color",
        )
    )
    async def channel_color(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        color: str | None = None,
    ) -> None:
        await _handle_channel_color(
            interaction,
            twitch_channel_login=twitch_channel_login,
            color=color,
            context=context,
        )

    tree.add_command(group)


async def _handle_channel_add(
    interaction: discord.Interaction,
    *,
    twitch_channel_login: str | None,
    context: _ChannelCommandContext,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.CHANNEL, step=UIFlowStep.ROOT):
        return
    normalized_login = twitch_channel_login.strip() if twitch_channel_login is not None else ""
    if not normalized_login:
        language = await context.ui_data_provider.get_thread_language(interaction.channel_id) or context.localizer.default_language
        await interaction.response.send_modal(
            ChannelNameModal(
                context=DiscordModalContext(
                    services=context.services,
                    discord_channel_id=interaction.channel_id,
                    requester_id=interaction.user.id,
                    localizer=context.localizer,
                    language=context.localizer.resolve_language(language),
                ),
            )
        )
        return
    result = await dispatch_add_tracked_channel(
        context.services,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        twitch_channel_login=normalized_login,
    )
    await send_initial_result(interaction, result)


async def _handle_channel_remove(
    interaction: discord.Interaction,
    *,
    twitch_channel_login: str | None,
    context: _ChannelCommandContext,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.CHANNEL, step=UIFlowStep.REMOVE):
        return
    normalized_login = twitch_channel_login.strip() if twitch_channel_login is not None else ""
    if not normalized_login:
        await _open_channel_selection_modal(
            interaction,
            context=context,
            action="remove",
        )
        return
    result = await dispatch_remove_tracked_channel(
        context.services,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        twitch_channel_login=normalized_login,
    )
    await send_initial_result(interaction, result)


async def _handle_channel_color(
    interaction: discord.Interaction,
    *,
    twitch_channel_login: str | None,
    color: str | None,
    context: _ChannelCommandContext,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.CHANNEL, step=UIFlowStep.COLOR):
        return
    normalized_login = twitch_channel_login.strip() if twitch_channel_login is not None else ""
    normalized_color = color.strip() if color is not None else None
    if not normalized_login:
        await _open_channel_selection_modal(
            interaction,
            context=context,
            action="color",
            default_login=normalized_login or None,
            default_color=normalized_color,
        )
        return
    result = await dispatch_set_tracked_channel_color(
        context.services,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        twitch_channel_login=normalized_login,
        color=normalized_color or None,
    )
    await send_initial_result(interaction, result)


async def _open_channel_selection_modal(
    interaction: discord.Interaction,
    *,
    context: _ChannelCommandContext,
    action: str,
    default_login: str | None = None,
    default_color: str | None = None,
) -> None:
    tracked_channels = await context.ui_data_provider.list_tracked_channels(interaction.channel_id)
    language = await context.ui_data_provider.get_thread_language(interaction.channel_id) or context.localizer.default_language
    if not tracked_channels:
        await send_initial_result(
            interaction,
            build_result(
                context.localizer,
                "discord.channel_ui.errors.no_channels",
                language=context.localizer.resolve_language(language),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            ),
        )
        return
    await interaction.response.send_modal(
        ChannelSelectionModal(
            context=DiscordModalContext(
                services=context.services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                localizer=context.localizer,
                language=context.localizer.resolve_language(language),
            ),
            action=action,
            tracked_channels=tracked_channels,
            default_login=default_login,
            default_color=default_color,
        )
    )
