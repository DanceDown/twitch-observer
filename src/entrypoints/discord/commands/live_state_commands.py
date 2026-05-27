"""Slash-command registration for tracked Twitch live/offline notifications."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle, StreamEventKind, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.services.twitch_runtime import DISCORD_NOTIFY_ACTION

from ..dispatch import (
    dispatch_add_channel_event,
    dispatch_disable_channel_event,
    dispatch_enable_channel_event,
    dispatch_remove_channel_event,
)
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.live_state_ui import ChannelEventActionModal, ChannelEventModal
from ..ui_data import AdapterEventActionPresentation, DiscordUIDataProvider


def register_live_state_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/liveping` and `/offlineping` action subcommands."""

    _register_live_state_group(
        tree=tree,
        services=services,
        ui_data_provider=ui_data_provider,
        localizer=localizer,
        root_name="liveping",
        description="Manage live notifications for this Discord channel.",
        state=StreamEventKind.ONLINE,
    )
    _register_live_state_group(
        tree=tree,
        services=services,
        ui_data_provider=ui_data_provider,
        localizer=localizer,
        root_name="offlineping",
        description="Manage offline notifications for this Discord channel.",
        state=StreamEventKind.OFFLINE,
    )


def _register_live_state_group(
    *,
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    root_name: str,
    description: str,
    state: StreamEventKind,
) -> None:
    group = discord.app_commands.Group(name=root_name, description=description)

    @group.command(name="add", description="Add one notification.")
    @discord.app_commands.describe(
        twitch_channel_login="Tracked Twitch channel login.",
        twitch_channel_id="Tracked Twitch channel ID (optional alternative to login).",
    )
    async def live_add(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        twitch_channel_id: str | None = None,
    ) -> None:
        await _handle_live_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.ADD_EVENT,
            action="add",
            state=state,
            twitch_channel_login=twitch_channel_login,
            twitch_channel_id=twitch_channel_id,
        )

    @group.command(name="remove", description="Remove one notification.")
    @discord.app_commands.describe(
        twitch_channel_login="Tracked Twitch channel login.",
        twitch_channel_id="Tracked Twitch channel ID (optional alternative to login).",
    )
    async def live_remove(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        twitch_channel_id: str | None = None,
    ) -> None:
        await _handle_live_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.REMOVE,
            action="remove",
            state=state,
            twitch_channel_login=twitch_channel_login,
            twitch_channel_id=twitch_channel_id,
        )

    @group.command(name="disable", description="Disable one notification.")
    @discord.app_commands.describe(
        twitch_channel_login="Tracked Twitch channel login.",
        twitch_channel_id="Tracked Twitch channel ID (optional alternative to login).",
    )
    async def live_disable(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        twitch_channel_id: str | None = None,
    ) -> None:
        await _handle_live_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.DISABLE,
            action="disable",
            state=state,
            twitch_channel_login=twitch_channel_login,
            twitch_channel_id=twitch_channel_id,
        )

    @group.command(name="enable", description="Enable one notification.")
    @discord.app_commands.describe(
        twitch_channel_login="Tracked Twitch channel login.",
        twitch_channel_id="Tracked Twitch channel ID (optional alternative to login).",
    )
    async def live_enable(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        twitch_channel_id: str | None = None,
    ) -> None:
        await _handle_live_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.ENABLE,
            action="enable",
            state=state,
            twitch_channel_login=twitch_channel_login,
            twitch_channel_id=twitch_channel_id,
        )

    tree.add_command(group)


async def _handle_live_action(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    step: UIFlowStep,
    action: str,
    state: StreamEventKind,
    twitch_channel_login: str | None,
    twitch_channel_id: str | None,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.LIVE, step=step):
        return

    normalized_login = (twitch_channel_login or "").strip().lower()
    normalized_id = (twitch_channel_id or "").strip()
    if action == "add" and not normalized_login and not normalized_id:
        tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
        if not tracked_channels:
            await send_initial_result(
                interaction,
                _live_result(interaction, ui_data_provider, localizer, "discord.live_state_ui.errors.no_channels"),
            )
            return
        await interaction.response.send_modal(
            ChannelEventModal(
                title=localizer.text(
                    f"discord.live_state_ui.modal.{state.value}.title",
                    language=_language(interaction, ui_data_provider, localizer),
                ),
                services=services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                tracked_channels=tracked_channels,
                event_key=state.value,
                localizer=localizer,
                language=_language(interaction, ui_data_provider, localizer),
            )
        )
        return
    if action != "add" and not normalized_login and not normalized_id:
        await _open_live_action_modal(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            action=action,
            state=state,
        )
        return

    resolved_channel_id = normalized_id
    if not resolved_channel_id:
        tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
        id_by_login = {item.login.lower(): item.user_id for item in tracked_channels}
        resolved_channel_id = id_by_login.get(normalized_login, normalized_login)

    if action == "add":
        result = await dispatch_add_channel_event(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_id=resolved_channel_id,
            event_kind=state,
        )
    elif action == "remove":
        result = await dispatch_remove_channel_event(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_id=resolved_channel_id,
            event_kind=state,
        )
    elif action == "disable":
        result = await dispatch_disable_channel_event(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_id=resolved_channel_id,
            event_kind=state,
        )
    else:
        result = await dispatch_enable_channel_event(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_id=resolved_channel_id,
            event_kind=state,
        )
    await send_initial_result(interaction, result)


async def _open_live_action_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    action: str,
    state: StreamEventKind,
) -> None:
    actions: list[AdapterEventActionPresentation] = [
        item
        for item in await ui_data_provider.list_adapter_event_actions(interaction.channel_id)
        if item.action.action_type == DISCORD_NOTIFY_ACTION and item.event.event.event_key == state.value
    ]
    if action == "disable":
        actions = [item for item in actions if not item.action.disabled]
    elif action == "enable":
        actions = [item for item in actions if item.action.disabled]
    if not actions:
        await send_initial_result(
            interaction,
            _live_result(
                interaction,
                ui_data_provider,
                localizer,
                f"discord.live_state_ui.errors.no_{action}_actions",
            ),
        )
        return
    await interaction.response.send_modal(
        ChannelEventActionModal(
            title=localizer.text(
                f"discord.live_state_ui.action.{action}_title",
                language=_language(interaction, ui_data_provider, localizer),
            ),
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action=action,
            actions=actions,
            localizer=localizer,
            language=_language(interaction, ui_data_provider, localizer),
        )
    )


def _language(
    interaction: discord.Interaction,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> str:
    return localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id))


def _live_result(
    interaction: discord.Interaction,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    key: str,
):
    return build_result(
        localizer,
        key,
        language=_language(interaction, ui_data_provider, localizer),
        style=DiscordResultStyle.ERROR,
        ephemeral=True,
    )
