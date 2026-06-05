"""Slash-command registration for tracked Twitch live/offline notifications."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle, StreamEventKind, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.services.twitch_runtime import DISCORD_NOTIFY_ACTION

from ..dispatch import dispatch_add_channel_event, dispatch_remove_channel_event, dispatch_set_channel_event_color
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
    state_choices = [
        discord.app_commands.Choice(name="live", value="online"),
        discord.app_commands.Choice(name="offline", value="offline"),
    ]

    @group.command(name="add", description="Add one live or offline ping.")
    @discord.app_commands.describe(
        twitch_channel_login="Tracked Twitch channel login.",
        state="Live or offline state.",
    )
    @discord.app_commands.choices(state=state_choices)
    async def live_add(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        state: discord.app_commands.Choice[str] | None = None,
    ) -> None:
        await _open_live_add_modal(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            default_channel_login=(twitch_channel_login or "").strip() or None,
            default_event_key=state.value if state is not None else None,
            run_direct=(twitch_channel_login or "").strip() != "" and state is not None,
        )

    @group.command(name="remove", description="Remove one live or offline ping.")
    @discord.app_commands.describe(ping_id="Ping ID or display index.")
    async def live_remove(interaction: discord.Interaction, ping_id: int | None = None) -> None:
        await _open_live_action_modal(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            action="remove",
            ping_id=ping_id,
        )

    @group.command(name="color", description="Set or clear the color for one live or offline ping.")
    @discord.app_commands.describe(
        ping_id="Ping ID or display index.",
        color="Hex color (leave empty to clear).",
    )
    async def live_color(
        interaction: discord.Interaction,
        ping_id: int | None = None,
        color: str | None = None,
    ) -> None:
        await _open_live_color_modal(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            ping_id=ping_id,
            default_color=(color or "").strip() or None,
        )

    tree.add_command(group)


async def _open_live_add_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    default_channel_login: str | None = None,
    default_event_key: str | None = None,
    run_direct: bool = False,
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
    if run_direct and default_channel_login and default_event_key:
        selected_channel = next((channel for channel in tracked_channels if channel.login == default_channel_login), None)
        if selected_channel is not None:
            result = await dispatch_add_channel_event(
                services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                twitch_channel_id=selected_channel.user_id,
                event_kind=StreamEventKind(default_event_key),
            )
            await send_initial_result(interaction, result)
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
            default_channel_id=default_channel_login,
            default_event_key=default_event_key,
        )
    )


async def _open_live_action_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    action: str,
    ping_id: int | None = None,
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
    selected_action = _resolve_notification_action(actions, ping_id)
    if selected_action is not None:
        result = await dispatch_remove_channel_event(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_id=selected_action.event.event.subject_id,
            event_kind=StreamEventKind(selected_action.event.event.event_key),
        )
        await send_initial_result(interaction, result)
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
            default_notification_value=_notification_value(selected_action),
        )
    )


async def _open_live_color_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    ping_id: int | None = None,
    default_color: str | None = None,
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
    selected_action = _resolve_notification_action(actions, ping_id)
    if selected_action is not None and ping_id is not None:
        result = await dispatch_set_channel_event_color(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_id=selected_action.event.event.subject_id,
            event_kind=StreamEventKind(selected_action.event.event.event_key),
            color=default_color,
        )
        await send_initial_result(interaction, result)
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
            default_notification_value=_notification_value(selected_action),
            default_color=default_color,
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


def _resolve_notification_action(
    actions: list[AdapterEventActionPresentation],
    ping_id: int | None,
) -> AdapterEventActionPresentation | None:
    if ping_id is None:
        return None
    for item in actions:
        if item.event.event.event_id == ping_id:
            return item
    for item in actions:
        if item.display_index == ping_id:
            return item
    return None


def _notification_value(item: AdapterEventActionPresentation | None) -> str | None:
    if item is None:
        return None
    return f"{item.event.event.subject_id}:{item.event.event.event_key}"
