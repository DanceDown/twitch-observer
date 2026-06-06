"""Slash-command registration for auto-reply management."""

from __future__ import annotations

import discord

from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..dispatch import dispatch_add_channel_event_reply, dispatch_add_pattern_reply
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui_data import DiscordUIDataProvider
from .reply_command_flows import (
    handle_event_reply_action,
    handle_pattern_reply_action,
    open_event_reply_add_modal,
    open_pattern_reply_add_modal,
)
from .reply_command_state import resolve_pattern_identifier


def register_reply_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/reply` action subcommands grouped by target type."""

    group = discord.app_commands.Group(
        name="reply",
        description="Add, remove, disable, or enable automatic replies.",
    )
    pattern_group = discord.app_commands.Group(
        name="pattern",
        description="Manage automatic replies attached to pings.",
        parent=group,
    )
    event_group = discord.app_commands.Group(
        name="event",
        description="Manage automatic replies attached to live or offline events.",
        parent=group,
    )

    @pattern_group.command(name="add", description="Add an auto-reply for one pattern.")
    @discord.app_commands.describe(
        pattern_id="Pattern ID or display index.",
        message="Reply text.",
        reply_as_reply="Send as Twitch threaded reply.",
    )
    async def reply_pattern_add(
        interaction: discord.Interaction,
        pattern_id: int | None = None,
        message: str | None = None,
        reply_as_reply: bool = False,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.REPLY, step=UIFlowStep.ADD_PATTERN):
            return
        normalized_message = message.strip() if message is not None else ""
        if pattern_id is None or not normalized_message:
            await open_pattern_reply_add_modal(
                interaction,
                services=services,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
                default_pattern_id=pattern_id,
                default_message=normalized_message or None,
                default_reply_as_reply=reply_as_reply,
            )
            return
        resolved_pattern_id = await resolve_pattern_identifier(ui_data_provider, interaction.channel_id, pattern_id)
        result = await dispatch_add_pattern_reply(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
            message=normalized_message,
            reply_as_reply=reply_as_reply,
        )
        await send_initial_result(interaction, result)

    @event_group.command(name="add", description="Add an auto-reply for one live/offline event.")
    @discord.app_commands.describe(
        event_id="Adapter event ID.",
        message="Reply text.",
    )
    async def reply_event_add(
        interaction: discord.Interaction,
        event_id: int | None = None,
        message: str | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.REPLY, step=UIFlowStep.ADD_EVENT):
            return
        normalized_message = message.strip() if message is not None else ""
        if event_id is None or not normalized_message:
            await open_event_reply_add_modal(
                interaction,
                services=services,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
                default_event_id=event_id,
                default_message=normalized_message or None,
            )
            return
        result = await dispatch_add_channel_event_reply(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_event_id=event_id,
            message=normalized_message,
            reply_as_reply=False,
        )
        await send_initial_result(interaction, result)

    @pattern_group.command(name="remove", description="Remove one pattern auto-reply.")
    @discord.app_commands.describe(pattern_id="Pattern ID or display index.")
    async def reply_pattern_remove(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_pattern_reply_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.REMOVE,
            action="remove",
            pattern_id=pattern_id,
        )

    @pattern_group.command(name="disable", description="Disable one pattern auto-reply.")
    @discord.app_commands.describe(pattern_id="Pattern ID or display index.")
    async def reply_pattern_disable(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_pattern_reply_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.DISABLE,
            action="disable",
            pattern_id=pattern_id,
        )

    @pattern_group.command(name="enable", description="Enable one pattern auto-reply.")
    @discord.app_commands.describe(pattern_id="Pattern ID or display index.")
    async def reply_pattern_enable(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_pattern_reply_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.ENABLE,
            action="enable",
            pattern_id=pattern_id,
        )

    @event_group.command(name="remove", description="Remove one event auto-reply.")
    @discord.app_commands.describe(event_id="Adapter event ID.")
    async def reply_event_remove(interaction: discord.Interaction, event_id: int | None = None) -> None:
        await handle_event_reply_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.REMOVE,
            action="remove",
            event_id=event_id,
        )

    @event_group.command(name="disable", description="Disable one event auto-reply.")
    @discord.app_commands.describe(event_id="Adapter event ID.")
    async def reply_event_disable(interaction: discord.Interaction, event_id: int | None = None) -> None:
        await handle_event_reply_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.DISABLE,
            action="disable",
            event_id=event_id,
        )

    @event_group.command(name="enable", description="Enable one event auto-reply.")
    @discord.app_commands.describe(event_id="Adapter event ID.")
    async def reply_event_enable(interaction: discord.Interaction, event_id: int | None = None) -> None:
        await handle_event_reply_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.ENABLE,
            action="enable",
            event_id=event_id,
        )

    tree.add_command(group)
