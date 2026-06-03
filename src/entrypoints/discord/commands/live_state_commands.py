"""Slash-command registration for tracked Twitch live/offline notifications."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.services.twitch_runtime import DISCORD_NOTIFY_ACTION

from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.live_state_ui import ChannelEventActionModal, ChannelEventColorModal, ChannelEventModal
from ..ui_data import AdapterEventActionPresentation, DiscordUIDataProvider


def register_live_state_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register one shared `/liveping` command group for live and offline pings."""

    group = discord.app_commands.Group(
        name="liveping",
        description="Manage live and offline pings for this Discord channel.",
    )

    @group.command(name="add", description="Add one live or offline ping.")
    async def live_add(interaction: discord.Interaction) -> None:
        await _open_live_add_modal(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
        )

    @group.command(name="remove", description="Remove one live or offline ping.")
    async def live_remove(interaction: discord.Interaction) -> None:
        await _open_live_action_modal(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            action="remove",
        )

    @group.command(name="color", description="Set or clear the color for one live or offline ping.")
    async def live_color(interaction: discord.Interaction) -> None:
        await _open_live_color_modal(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
        )

    tree.add_command(group)


async def _open_live_add_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.LIVE, step=UIFlowStep.ADD_EVENT):
        return

    tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
    language = await _language(interaction, ui_data_provider, localizer)
    if not tracked_channels:
        await send_initial_result(
            interaction,
            _live_result(localizer, language, "discord.live_state_ui.errors.no_channels"),
        )
        return

    await interaction.response.send_modal(
        ChannelEventModal(
            title=localizer.text(
                "discord.live_state_ui.modal.add_title",
                language=language,
            ),
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            tracked_channels=tracked_channels,
            localizer=localizer,
            language=language,
        )
    )


async def _open_live_action_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    action: str,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.LIVE, step=UIFlowStep.REMOVE):
        return

    actions = await _list_notification_actions(interaction.channel_id, ui_data_provider=ui_data_provider)
    language = await _language(interaction, ui_data_provider, localizer)
    if not actions:
        await send_initial_result(
            interaction,
            _live_result(localizer, language, f"discord.live_state_ui.errors.no_{action}_actions"),
        )
        return
    await interaction.response.send_modal(
        ChannelEventActionModal(
            title=localizer.text(
                f"discord.live_state_ui.action.{action}_title",
                language=language,
            ),
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action=action,
            actions=actions,
            localizer=localizer,
            language=language,
        )
    )


async def _open_live_color_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.LIVE, step=UIFlowStep.COLOR):
        return

    actions = await _list_notification_actions(interaction.channel_id, ui_data_provider=ui_data_provider)
    language = await _language(interaction, ui_data_provider, localizer)
    if not actions:
        await send_initial_result(
            interaction,
            _live_result(localizer, language, "discord.live_state_ui.errors.no_color_actions"),
        )
        return

    await interaction.response.send_modal(
        ChannelEventColorModal(
            title=localizer.text(
                "discord.live_state_ui.action.color_title",
                language=language,
            ),
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            actions=actions,
            localizer=localizer,
            language=language,
        )
    )


async def _list_notification_actions(
    discord_channel_id: int,
    *,
    ui_data_provider: DiscordUIDataProvider,
) -> list[AdapterEventActionPresentation]:
    return [
        item
        for item in await ui_data_provider.list_adapter_event_actions(discord_channel_id)
        if item.action.action_type == DISCORD_NOTIFY_ACTION
    ]


async def _language(
    interaction: discord.Interaction,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> str:
    return localizer.resolve_language(await ui_data_provider.get_thread_language(interaction.channel_id))


def _live_result(
    localizer: Localizer,
    language: str,
    key: str,
):
    return build_result(
        localizer,
        key,
        language=language,
        style=DiscordResultStyle.ERROR,
        ephemeral=True,
    )
