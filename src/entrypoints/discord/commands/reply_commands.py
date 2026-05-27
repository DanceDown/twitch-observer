"""Slash-command registration for auto-reply management."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.services.twitch_runtime import TWITCH_SEND_MESSAGE_ACTION

from ..dispatch import (
    dispatch_add_channel_event_reply,
    dispatch_add_pattern_reply,
    dispatch_disable_channel_event_reply,
    dispatch_disable_pattern_reply,
    dispatch_enable_channel_event_reply,
    dispatch_enable_pattern_reply,
    dispatch_remove_channel_event_reply,
    dispatch_remove_pattern_reply,
)
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.reply_ui import EventReplyAddModal, PatternReplyAddModal, ReplyActionModal
from ..ui_data import DiscordUIDataProvider


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
            await _open_pattern_reply_add_modal(
                interaction,
                services=services,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
                default_pattern_id=pattern_id,
                default_message=normalized_message or None,
                default_reply_as_reply=reply_as_reply,
            )
            return
        resolved_pattern_id = await _resolve_pattern_identifier(ui_data_provider, interaction.channel_id, pattern_id)
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
            await _open_event_reply_add_modal(
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
        await _handle_pattern_reply_action(
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
        await _handle_pattern_reply_action(
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
        await _handle_pattern_reply_action(
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
        await _handle_event_reply_action(
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
        await _handle_event_reply_action(
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
        await _handle_event_reply_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.ENABLE,
            action="enable",
            event_id=event_id,
        )

    tree.add_command(group)


async def _handle_pattern_reply_action(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    step: UIFlowStep,
    action: str,
    pattern_id: int | None,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.REPLY, step=step):
        return
    if pattern_id is None:
        replies = list(await ui_data_provider.list_replies(interaction.channel_id))
        if action == "disable":
            replies = [reply for reply in replies if not reply.reply.disabled]
        elif action == "enable":
            replies = [reply for reply in replies if reply.reply.disabled]
        if not replies:
            await send_initial_result(
                interaction,
                _reply_result(interaction, ui_data_provider, localizer, "discord.reply_ui.errors.no_replies"),
            )
            return
        await interaction.response.send_modal(
            ReplyActionModal(
                title=_localized_reply_action_title(interaction, ui_data_provider, localizer, action),
                services=services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                action=action,
                replies=replies,
                localizer=localizer,
                language=_language(interaction, ui_data_provider, localizer),
            )
        )
        return
    resolved_pattern_id = await _resolve_pattern_identifier(ui_data_provider, interaction.channel_id, pattern_id)
    if action == "remove":
        result = await dispatch_remove_pattern_reply(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    elif action == "disable":
        result = await dispatch_disable_pattern_reply(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    else:
        result = await dispatch_enable_pattern_reply(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    await send_initial_result(interaction, result)


async def _handle_event_reply_action(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    step: UIFlowStep,
    action: str,
    event_id: int | None,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.REPLY, step=step):
        return
    if event_id is None:
        replies = [
            reply
            for reply in await ui_data_provider.list_adapter_event_actions(interaction.channel_id)
            if reply.action.action_type == TWITCH_SEND_MESSAGE_ACTION
        ]
        if action == "disable":
            replies = [reply for reply in replies if not reply.action.disabled]
        elif action == "enable":
            replies = [reply for reply in replies if reply.action.disabled]
        if not replies:
            await send_initial_result(
                interaction,
                _reply_result(interaction, ui_data_provider, localizer, "discord.reply_ui.errors.no_replies"),
            )
            return
        await interaction.response.send_modal(
            ReplyActionModal(
                title=_localized_reply_action_title(interaction, ui_data_provider, localizer, action),
                services=services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                action=action,
                replies=replies,
                localizer=localizer,
                language=_language(interaction, ui_data_provider, localizer),
            )
        )
        return
    if action == "remove":
        result = await dispatch_remove_channel_event_reply(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_event_id=event_id,
        )
    elif action == "disable":
        result = await dispatch_disable_channel_event_reply(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_event_id=event_id,
        )
    else:
        result = await dispatch_enable_channel_event_reply(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_event_id=event_id,
        )
    await send_initial_result(interaction, result)


async def _resolve_pattern_identifier(
    ui_data_provider: DiscordUIDataProvider,
    discord_channel_id: int,
    pattern_id: int,
) -> int:
    patterns = await ui_data_provider.list_patterns(discord_channel_id)
    for item in patterns:
        if item.pattern.pattern_id == pattern_id:
            return item.pattern.pattern_id
    for item in patterns:
        if item.display_index == pattern_id:
            return item.pattern.pattern_id
    return pattern_id


async def _open_pattern_reply_add_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    default_pattern_id: int | None = None,
    default_message: str | None = None,
    default_reply_as_reply: bool = False,
) -> None:
    patterns = await ui_data_provider.list_patterns(interaction.channel_id)
    if not patterns:
        await send_initial_result(
            interaction,
            _reply_result(interaction, ui_data_provider, localizer, "discord.reply_ui.errors.no_patterns"),
        )
        return
    resolved_pattern_id = None
    if default_pattern_id is not None:
        resolved_pattern_id = await _resolve_pattern_identifier(ui_data_provider, interaction.channel_id, default_pattern_id)
    await interaction.response.send_modal(
        PatternReplyAddModal(
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            patterns=patterns,
            localizer=localizer,
            language=_language(interaction, ui_data_provider, localizer),
            default_pattern_id=resolved_pattern_id,
            default_message=default_message,
            default_reply_as_reply=default_reply_as_reply,
        )
    )


async def _open_event_reply_add_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    default_event_id: int | None = None,
    default_message: str | None = None,
) -> None:
    adapter_events = await ui_data_provider.list_adapter_events(interaction.channel_id)
    if not adapter_events:
        await send_initial_result(
            interaction,
            _reply_result(interaction, ui_data_provider, localizer, "discord.reply_ui.errors.no_event_triggers"),
        )
        return
    await interaction.response.send_modal(
        EventReplyAddModal(
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_events=adapter_events,
            localizer=localizer,
            language=_language(interaction, ui_data_provider, localizer),
            default_event_id=default_event_id,
            default_message=default_message,
        )
    )


def _language(
    interaction: discord.Interaction,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> str:
    return localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id))


def _localized_reply_action_title(
    interaction: discord.Interaction,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    action: str,
) -> str:
    return localizer.text(
        f"discord.reply_ui.action.{action}_title",
        language=_language(interaction, ui_data_provider, localizer),
    )


def _reply_result(
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
