"""UI flow helpers for reply command entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

import discord

from src.discord_results import build_result
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.services.twitch_runtime import TWITCH_SEND_MESSAGE_ACTION

from ..dispatch import (
    dispatch_disable_channel_event_reply,
    dispatch_disable_pattern_reply,
    dispatch_enable_channel_event_reply,
    dispatch_enable_pattern_reply,
    dispatch_remove_channel_event_reply,
    dispatch_remove_pattern_reply,
)
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.reply_ui import EventReplyAddModal, PatternReplyAddModal, ReplyActionModal
from ..ui.shared import DiscordModalContext
from ..ui_data import DiscordUIDataProvider
from .reply_command_state import resolve_pattern_identifier


@dataclass(slots=True, frozen=True)
class ReplyFlowContext:
    """Shared dependencies for reply command UI/direct-action flows."""

    services: DiscordServiceBundle
    data_provider: DiscordUIDataProvider
    localizer: Localizer


async def handle_pattern_reply_action(
    interaction: discord.Interaction,
    *,
    context: ReplyFlowContext,
    step: UIFlowStep,
    action: str,
    pattern_id: int | None,
) -> None:
    """Run a direct or modal-driven pattern reply action."""
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.REPLY, step=step):
        return
    if pattern_id is None:
        language = await language_for_interaction(interaction, context.data_provider, context.localizer)
        replies = list(await context.data_provider.list_replies(interaction.channel_id))
        if action == "disable":
            replies = [reply for reply in replies if not reply.reply.disabled]
        elif action == "enable":
            replies = [reply for reply in replies if reply.reply.disabled]
        if not replies:
            await send_initial_result(
                interaction,
                reply_result(context.localizer, language, "discord.reply_ui.errors.no_replies"),
            )
            return
        await interaction.response.send_modal(
            ReplyActionModal(
                title=localized_reply_action_title(context.localizer, language, action),
                context=DiscordModalContext(
                    services=context.services,
                    discord_channel_id=interaction.channel_id,
                    requester_id=interaction.user.id,
                    localizer=context.localizer,
                    language=language,
                ),
                action=action,
                replies=replies,
            )
        )
        return
    resolved_pattern_id = await resolve_pattern_identifier(context.data_provider, interaction.channel_id, pattern_id)
    if action == "remove":
        result = await dispatch_remove_pattern_reply(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    elif action == "disable":
        result = await dispatch_disable_pattern_reply(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    else:
        result = await dispatch_enable_pattern_reply(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    await send_initial_result(interaction, result)


async def handle_event_reply_action(
    interaction: discord.Interaction,
    *,
    context: ReplyFlowContext,
    step: UIFlowStep,
    action: str,
    event_id: int | None,
) -> None:
    """Run a direct or modal-driven live/offline reply action."""
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.REPLY, step=step):
        return
    if event_id is None:
        language = await language_for_interaction(interaction, context.data_provider, context.localizer)
        replies = [
            reply
            for reply in await context.data_provider.list_adapter_event_actions(interaction.channel_id)
            if reply.action.action_type == TWITCH_SEND_MESSAGE_ACTION
        ]
        if action == "disable":
            replies = [reply for reply in replies if not reply.action.disabled]
        elif action == "enable":
            replies = [reply for reply in replies if reply.action.disabled]
        if not replies:
            await send_initial_result(
                interaction,
                reply_result(context.localizer, language, "discord.reply_ui.errors.no_replies"),
            )
            return
        await interaction.response.send_modal(
            ReplyActionModal(
                title=localized_reply_action_title(context.localizer, language, action),
                context=DiscordModalContext(
                    services=context.services,
                    discord_channel_id=interaction.channel_id,
                    requester_id=interaction.user.id,
                    localizer=context.localizer,
                    language=language,
                ),
                action=action,
                replies=replies,
            )
        )
        return
    if action == "remove":
        result = await dispatch_remove_channel_event_reply(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_event_id=event_id,
        )
    elif action == "disable":
        result = await dispatch_disable_channel_event_reply(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_event_id=event_id,
        )
    else:
        result = await dispatch_enable_channel_event_reply(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_event_id=event_id,
        )
    await send_initial_result(interaction, result)


async def open_pattern_reply_add_modal(
    interaction: discord.Interaction,
    *,
    context: ReplyFlowContext,
    default_pattern_id: int | None = None,
    default_message: str | None = None,
    default_reply_as_reply: bool = False,
) -> None:
    """Open the modal that attaches an auto-reply to a pattern."""
    patterns = await context.data_provider.list_patterns(interaction.channel_id)
    language = await language_for_interaction(interaction, context.data_provider, context.localizer)
    if not patterns:
        await send_initial_result(
            interaction,
            reply_result(context.localizer, language, "discord.reply_ui.errors.no_patterns"),
        )
        return
    resolved_pattern_id = None
    if default_pattern_id is not None:
        resolved_pattern_id = await resolve_pattern_identifier(context.data_provider, interaction.channel_id, default_pattern_id)
    await interaction.response.send_modal(
        PatternReplyAddModal(
            context=DiscordModalContext(
                services=context.services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                localizer=context.localizer,
                language=language,
            ),
            patterns=patterns,
            default_pattern_id=resolved_pattern_id,
            default_message=default_message,
            default_reply_as_reply=default_reply_as_reply,
        )
    )


async def open_event_reply_add_modal(
    interaction: discord.Interaction,
    *,
    context: ReplyFlowContext,
    default_event_id: int | None = None,
    default_message: str | None = None,
) -> None:
    """Open the modal that attaches an auto-reply to a live/offline event."""
    adapter_events = await context.data_provider.list_adapter_events(interaction.channel_id)
    language = await language_for_interaction(interaction, context.data_provider, context.localizer)
    if not adapter_events:
        await send_initial_result(
            interaction,
            reply_result(context.localizer, language, "discord.reply_ui.errors.no_event_triggers"),
        )
        return
    await interaction.response.send_modal(
        EventReplyAddModal(
            context=DiscordModalContext(
                services=context.services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                localizer=context.localizer,
                language=language,
            ),
            adapter_events=adapter_events,
            default_event_id=default_event_id,
            default_message=default_message,
        )
    )


async def language_for_interaction(
    interaction: discord.Interaction,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> str:
    """Resolve the language configured for the interaction's Discord context."""
    return localizer.resolve_language(await ui_data_provider.get_thread_language(interaction.channel_id))


def localized_reply_action_title(
    localizer: Localizer,
    language: str,
    action: str,
) -> str:
    """Return the localized modal title for one reply action."""
    return localizer.text(
        f"discord.reply_ui.action.{action}_title",
        language=language,
    )


def reply_result(
    localizer: Localizer,
    language: str,
    key: str,
) -> DiscordCommandResult:
    """Build an ephemeral reply-flow error result."""
    return build_result(
        localizer,
        key,
        language=language,
        style=DiscordResultStyle.ERROR,
        ephemeral=True,
    )
