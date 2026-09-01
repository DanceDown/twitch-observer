"""Slash-command registration for tracked Twitch live/offline notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import discord

from src.discord_results import build_result
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import SetChannelEventColorCommand
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.twitch_events import StreamEventKind
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.services.twitch_runtime import DISCORD_NOTIFY_ACTION

from ..dispatch import dispatch_add_channel_event, dispatch_remove_channel_event, dispatch_set_channel_event_color
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.live_state_ui import ChannelEventActionModal, ChannelEventColorModal, ChannelEventModal
from ..ui.shared import DiscordModalContext
from ..ui_data import AdapterEventActionPresentation, TrackedChannelPresentation
from .localized import command_descriptions, command_text


class LiveStateCommandDataProvider(Protocol):
    """Read-side data needed by `/liveping` before opening a modal."""

    async def get_thread_language(self, discord_channel_id: int) -> str | None:
        """Return the configured language for a Discord context."""
        ...

    async def list_tracked_channels(self, discord_channel_id: int) -> list[TrackedChannelPresentation]:
        """Return tracked Twitch channels for the context."""
        ...

    async def list_adapter_event_actions(self, discord_channel_id: int) -> list[AdapterEventActionPresentation]:
        """Return live/offline event actions for the context."""
        ...


@dataclass(slots=True, frozen=True)
class LiveStateCommandContext:
    """Shared dependencies for `/liveping` command handlers."""

    services: DiscordServiceBundle
    data_provider: LiveStateCommandDataProvider
    localizer: Localizer


def register_live_state_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: LiveStateCommandDataProvider,
    localizer: Localizer,
) -> None:
    """Register one shared `/liveping` command group for live and offline pings."""
    group = discord.app_commands.Group(
        name="liveping",
        description=command_text(localizer, "liveping.description"),
    )
    state_choices = [
        discord.app_commands.Choice(name=command_text(localizer, "liveping.choices.live"), value=StreamEventKind.ONLINE.value),
        discord.app_commands.Choice(name=command_text(localizer, "liveping.choices.offline"), value=StreamEventKind.OFFLINE.value),
    ]
    context = LiveStateCommandContext(services=services, data_provider=ui_data_provider, localizer=localizer)

    @group.command(name="add", description=command_text(localizer, "liveping.add.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            twitch_channel_login="liveping.add.options.twitch_channel_login",
            state="liveping.add.options.state",
        )
    )
    @discord.app_commands.choices(state=state_choices)
    async def live_add(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        state: discord.app_commands.Choice[str] | None = None,
    ) -> None:
        await _open_live_add_modal(
            interaction,
            context=context,
            default_channel_login=(twitch_channel_login or "").strip() or None,
            default_event_key=state.value if state is not None else None,
            run_direct=(twitch_channel_login or "").strip() != "" and state is not None,
        )

    @group.command(name="remove", description=command_text(localizer, "liveping.remove.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, ping_id="liveping.remove.options.ping_id"))
    async def live_remove(interaction: discord.Interaction, ping_id: int | None = None) -> None:
        await _open_live_action_modal(
            interaction,
            context=context,
            action="remove",
            ping_id=ping_id,
        )

    @group.command(name="color", description=command_text(localizer, "liveping.color.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            ping_id="liveping.color.options.ping_id",
            color="liveping.color.options.color",
        )
    )
    async def live_color(
        interaction: discord.Interaction,
        ping_id: int | None = None,
        color: str | None = None,
    ) -> None:
        await _open_live_color_modal(
            interaction,
            context=context,
            ping_id=ping_id,
            default_color=(color or "").strip() or None,
        )

    tree.add_command(group)


async def _open_live_add_modal(
    interaction: discord.Interaction,
    *,
    context: LiveStateCommandContext,
    default_channel_login: str | None = None,
    default_event_key: str | None = None,
    run_direct: bool = False,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.LIVE, step=UIFlowStep.ADD_EVENT):
        return

    tracked_channels = await context.data_provider.list_tracked_channels(interaction.channel_id)
    language = await _language(interaction, context.data_provider, context.localizer)
    if not tracked_channels:
        await send_initial_result(
            interaction,
            _live_result(context.localizer, language, "discord.live_state_ui.errors.no_channels"),
        )
        return
    if run_direct and default_channel_login and default_event_key:
        selected_channel = next((channel for channel in tracked_channels if channel.login == default_channel_login), None)
        if selected_channel is not None:
            result = await dispatch_add_channel_event(
                context.services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                twitch_channel_id=selected_channel.user_id,
                event_kind=StreamEventKind(default_event_key),
            )
            await send_initial_result(interaction, result)
            return

    await interaction.response.send_modal(
        ChannelEventModal(
            title=context.localizer.text(
                "discord.live_state_ui.modal.add_title",
                language=language,
            ),
            context=DiscordModalContext(
                services=context.services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                localizer=context.localizer,
                language=language,
            ),
            tracked_channels=tracked_channels,
            default_channel_id=default_channel_login,
            default_event_key=default_event_key,
        )
    )


async def _open_live_action_modal(
    interaction: discord.Interaction,
    *,
    context: LiveStateCommandContext,
    action: str,
    ping_id: int | None = None,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.LIVE, step=UIFlowStep.REMOVE):
        return

    actions = await _list_notification_actions(interaction.channel_id, ui_data_provider=context.data_provider)
    language = await _language(interaction, context.data_provider, context.localizer)
    if not actions:
        await send_initial_result(
            interaction,
            _live_result(context.localizer, language, f"discord.live_state_ui.errors.no_{action}_actions"),
        )
        return
    selected_action = _resolve_notification_action(actions, ping_id)
    if selected_action is not None:
        result = await dispatch_remove_channel_event(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_channel_id=selected_action.event.event.subject_id,
            event_kind=StreamEventKind(selected_action.event.event.event_key),
        )
        await send_initial_result(interaction, result)
        return
    await interaction.response.send_modal(
        ChannelEventActionModal(
            title=context.localizer.text(
                f"discord.live_state_ui.action.{action}_title",
                language=language,
            ),
            context=DiscordModalContext(
                services=context.services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                localizer=context.localizer,
                language=language,
            ),
            action=action,
            actions=actions,
            default_notification_value=_notification_value(selected_action),
        )
    )


async def _open_live_color_modal(
    interaction: discord.Interaction,
    *,
    context: LiveStateCommandContext,
    ping_id: int | None = None,
    default_color: str | None = None,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.LIVE, step=UIFlowStep.COLOR):
        return

    actions = await _list_notification_actions(interaction.channel_id, ui_data_provider=context.data_provider)
    language = await _language(interaction, context.data_provider, context.localizer)
    if not actions:
        await send_initial_result(
            interaction,
            _live_result(context.localizer, language, "discord.live_state_ui.errors.no_color_actions"),
        )
        return
    selected_action = _resolve_notification_action(actions, ping_id)
    if selected_action is not None and ping_id is not None:
        result = await dispatch_set_channel_event_color(
            context.services,
            SetChannelEventColorCommand(
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                twitch_channel_id=selected_action.event.event.subject_id,
                event_kind=StreamEventKind(selected_action.event.event.event_key),
                color=default_color,
            ),
        )
        await send_initial_result(interaction, result)
        return

    await interaction.response.send_modal(
        ChannelEventColorModal(
            title=context.localizer.text(
                "discord.live_state_ui.action.color_title",
                language=language,
            ),
            context=DiscordModalContext(
                services=context.services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                localizer=context.localizer,
                language=language,
            ),
            actions=actions,
            default_notification_value=_notification_value(selected_action),
            default_color=default_color,
        )
    )


async def _list_notification_actions(
    discord_channel_id: int,
    *,
    ui_data_provider: LiveStateCommandDataProvider,
) -> list[AdapterEventActionPresentation]:
    return [
        item
        for item in await ui_data_provider.list_adapter_event_actions(discord_channel_id)
        if item.action.action_type == DISCORD_NOTIFY_ACTION
    ]


async def _language(
    interaction: discord.Interaction,
    ui_data_provider: LiveStateCommandDataProvider,
    localizer: Localizer,
) -> str:
    return localizer.resolve_language(await ui_data_provider.get_thread_language(interaction.channel_id))


def _live_result(
    localizer: Localizer,
    language: str,
    key: str,
) -> DiscordCommandResult:
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
