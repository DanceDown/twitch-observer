"""Slash-command registration for tracked Twitch channels."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle
from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..dispatch import dispatch_add_tracked_channel, dispatch_remove_tracked_channel, dispatch_set_tracked_channel_color
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.channel_ui import ChannelNameModal, ChannelSelectionModal
from ..ui_data import DiscordUIDataProvider


def register_channel_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/channel` action subcommands."""

    group = discord.app_commands.Group(name="channel", description="Add, remove, or recolor tracked Twitch channels.")

    @group.command(name="add", description="Add one tracked Twitch channel.")
    @discord.app_commands.describe(twitch_channel_login="Twitch channel login.")
    async def channel_add(interaction: discord.Interaction, twitch_channel_login: str | None = None) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.CHANNEL, step=UIFlowStep.ROOT):
            return
        normalized_login = twitch_channel_login.strip() if twitch_channel_login is not None else ""
        if not normalized_login:
            await interaction.response.send_modal(
                ChannelNameModal(
                    services=services,
                    discord_channel_id=interaction.channel_id,
                    requester_id=interaction.user.id,
                    action="add",
                    localizer=localizer,
                    language=localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id)),
                )
            )
            return
        result = await dispatch_add_tracked_channel(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_login=normalized_login,
        )
        await send_initial_result(interaction, result)

    @group.command(name="remove", description="Remove one tracked Twitch channel.")
    @discord.app_commands.describe(twitch_channel_login="Tracked Twitch channel login.")
    async def channel_remove(interaction: discord.Interaction, twitch_channel_login: str | None = None) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.CHANNEL, step=UIFlowStep.REMOVE):
            return
        normalized_login = twitch_channel_login.strip() if twitch_channel_login is not None else ""
        if not normalized_login:
            await _open_channel_selection_modal(
                interaction,
                services=services,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
                action="remove",
            )
            return
        result = await dispatch_remove_tracked_channel(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_login=normalized_login,
        )
        await send_initial_result(interaction, result)

    @group.command(name="color", description="Set or clear the color for one tracked channel.")
    @discord.app_commands.describe(
        twitch_channel_login="Tracked Twitch channel login.",
        color="Hex color (leave empty to clear).",
    )
    async def channel_color(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        color: str | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.CHANNEL, step=UIFlowStep.COLOR):
            return
        normalized_login = twitch_channel_login.strip() if twitch_channel_login is not None else ""
        normalized_color = color.strip() if color is not None else None
        if not normalized_login:
            await _open_channel_selection_modal(
                interaction,
                services=services,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
                action="color",
                default_login=normalized_login or None,
                default_color=normalized_color,
            )
            return
        result = await dispatch_set_tracked_channel_color(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_login=normalized_login,
            color=normalized_color or None,
        )
        await send_initial_result(interaction, result)

    tree.add_command(group)


async def _open_channel_selection_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    action: str,
    default_login: str | None = None,
    default_color: str | None = None,
) -> None:
    tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
    if not tracked_channels:
        await send_initial_result(
            interaction,
            build_result(
                localizer,
                "discord.channel_ui.errors.no_channels",
                language=localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id)),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            ),
        )
        return
    await interaction.response.send_modal(
        ChannelSelectionModal(
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action=action,
            tracked_channels=tracked_channels,
            localizer=localizer,
            language=localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id)),
            default_login=default_login,
            default_color=default_color,
        )
    )
