"""Slash-command registration for auto-reply management."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import AddChannelEventReplyCommand, AddPatternReplyCommand
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_add_channel_event_reply, dispatch_add_pattern_reply
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text
from .reply_command_flows import (
    ReplyFlowContext,
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
        description=command_text(localizer, "reply.description"),
    )
    pattern_group = discord.app_commands.Group(
        name="pattern",
        description=command_text(localizer, "reply.pattern.description"),
        parent=group,
    )
    event_group = discord.app_commands.Group(
        name="event",
        description=command_text(localizer, "reply.event.description"),
        parent=group,
    )
    context = ReplyFlowContext(services=services, data_provider=ui_data_provider, localizer=localizer)

    @pattern_group.command(name="add", description=command_text(localizer, "reply.pattern.add.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            pattern_id="reply.pattern.add.options.pattern_id",
            message="reply.pattern.add.options.message",
            reply_as_reply="reply.pattern.add.options.reply_as_reply",
        )
    )
    async def reply_pattern_add(
        interaction: discord.Interaction,
        *,
        pattern_id: int | None = None,
        message: str | None = None,
        reply_as_reply: bool = False,
    ) -> None:
        await _handle_reply_pattern_add(
            interaction,
            pattern_id=pattern_id,
            message=message,
            reply_as_reply=reply_as_reply,
            context=context,
        )

    @event_group.command(name="add", description=command_text(localizer, "reply.event.add.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            event_id="reply.event.add.options.event_id",
            message="reply.event.add.options.message",
        )
    )
    async def reply_event_add(
        interaction: discord.Interaction,
        event_id: int | None = None,
        message: str | None = None,
    ) -> None:
        await _handle_reply_event_add(
            interaction,
            event_id=event_id,
            message=message,
            context=context,
        )

    @pattern_group.command(name="remove", description=command_text(localizer, "reply.pattern.remove.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, pattern_id="reply.pattern.remove.options.pattern_id"))
    async def reply_pattern_remove(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_pattern_reply_action(
            interaction,
            context=context,
            step=UIFlowStep.REMOVE,
            action="remove",
            pattern_id=pattern_id,
        )

    @pattern_group.command(name="disable", description=command_text(localizer, "reply.pattern.disable.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, pattern_id="reply.pattern.disable.options.pattern_id"))
    async def reply_pattern_disable(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_pattern_reply_action(
            interaction,
            context=context,
            step=UIFlowStep.DISABLE,
            action="disable",
            pattern_id=pattern_id,
        )

    @pattern_group.command(name="enable", description=command_text(localizer, "reply.pattern.enable.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, pattern_id="reply.pattern.enable.options.pattern_id"))
    async def reply_pattern_enable(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_pattern_reply_action(
            interaction,
            context=context,
            step=UIFlowStep.ENABLE,
            action="enable",
            pattern_id=pattern_id,
        )

    @event_group.command(name="remove", description=command_text(localizer, "reply.event.remove.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, event_id="reply.event.remove.options.event_id"))
    async def reply_event_remove(interaction: discord.Interaction, event_id: int | None = None) -> None:
        await handle_event_reply_action(
            interaction,
            context=context,
            step=UIFlowStep.REMOVE,
            action="remove",
            event_id=event_id,
        )

    @event_group.command(name="disable", description=command_text(localizer, "reply.event.disable.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, event_id="reply.event.disable.options.event_id"))
    async def reply_event_disable(interaction: discord.Interaction, event_id: int | None = None) -> None:
        await handle_event_reply_action(
            interaction,
            context=context,
            step=UIFlowStep.DISABLE,
            action="disable",
            event_id=event_id,
        )

    @event_group.command(name="enable", description=command_text(localizer, "reply.event.enable.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, event_id="reply.event.enable.options.event_id"))
    async def reply_event_enable(interaction: discord.Interaction, event_id: int | None = None) -> None:
        await handle_event_reply_action(
            interaction,
            context=context,
            step=UIFlowStep.ENABLE,
            action="enable",
            event_id=event_id,
        )

    tree.add_command(group)


async def _handle_reply_pattern_add(
    interaction: discord.Interaction,
    *,
    pattern_id: int | None,
    message: str | None,
    reply_as_reply: bool,
    context: ReplyFlowContext,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.REPLY, step=UIFlowStep.ADD_PATTERN):
        return
    normalized_message = message.strip() if message is not None else ""
    if pattern_id is None or not normalized_message:
        await open_pattern_reply_add_modal(
            interaction,
            context=context,
            default_pattern_id=pattern_id,
            default_message=normalized_message or None,
            default_reply_as_reply=reply_as_reply,
        )
        return
    resolved_pattern_id = await resolve_pattern_identifier(context.data_provider, interaction.channel_id, pattern_id)
    result = await dispatch_add_pattern_reply(
        context.services,
        AddPatternReplyCommand(
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
            message=normalized_message,
            reply_as_reply=reply_as_reply,
        ),
    )
    await send_initial_result(interaction, result)


async def _handle_reply_event_add(
    interaction: discord.Interaction,
    *,
    event_id: int | None,
    message: str | None,
    context: ReplyFlowContext,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.REPLY, step=UIFlowStep.ADD_EVENT):
        return
    normalized_message = message.strip() if message is not None else ""
    if event_id is None or not normalized_message:
        await open_event_reply_add_modal(
            interaction,
            context=context,
            default_event_id=event_id,
            default_message=normalized_message or None,
        )
        return
    result = await dispatch_add_channel_event_reply(
        context.services,
        AddChannelEventReplyCommand(
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_event_id=event_id,
            message=normalized_message,
            reply_as_reply=False,
        ),
    )
    await send_initial_result(interaction, result)
