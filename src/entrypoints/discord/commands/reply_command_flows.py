"""UI flow helpers for reply command entrypoints."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
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
from ..ui_data import DiscordUIDataProvider
from .reply_command_state import resolve_pattern_identifier


async def handle_pattern_reply_action(
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
        language = await language_for_interaction(interaction, ui_data_provider, localizer)
        replies = list(await ui_data_provider.list_replies(interaction.channel_id))
        if action == "disable":
            replies = [reply for reply in replies if not reply.reply.disabled]
        elif action == "enable":
            replies = [reply for reply in replies if reply.reply.disabled]
        if not replies:
            await send_initial_result(
                interaction,
                reply_result(localizer, language, "discord.reply_ui.errors.no_replies"),
            )
            return
        await interaction.response.send_modal(
            ReplyActionModal(
                title=localized_reply_action_title(localizer, language, action),
                services=services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                action=action,
                replies=replies,
                localizer=localizer,
                language=language,
            )
        )
        return
    resolved_pattern_id = await resolve_pattern_identifier(ui_data_provider, interaction.channel_id, pattern_id)
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


async def handle_event_reply_action(
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
        language = await language_for_interaction(interaction, ui_data_provider, localizer)
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
                reply_result(localizer, language, "discord.reply_ui.errors.no_replies"),
            )
            return
        await interaction.response.send_modal(
            ReplyActionModal(
                title=localized_reply_action_title(localizer, language, action),
                services=services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                action=action,
                replies=replies,
                localizer=localizer,
                language=language,
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


async def open_pattern_reply_add_modal(
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
    language = await language_for_interaction(interaction, ui_data_provider, localizer)
    if not patterns:
        await send_initial_result(
            interaction,
            reply_result(localizer, language, "discord.reply_ui.errors.no_patterns"),
        )
        return
    resolved_pattern_id = None
    if default_pattern_id is not None:
        resolved_pattern_id = await resolve_pattern_identifier(ui_data_provider, interaction.channel_id, default_pattern_id)
    await interaction.response.send_modal(
        PatternReplyAddModal(
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            patterns=patterns,
            localizer=localizer,
            language=language,
            default_pattern_id=resolved_pattern_id,
            default_message=default_message,
            default_reply_as_reply=default_reply_as_reply,
        )
    )


async def open_event_reply_add_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    default_event_id: int | None = None,
    default_message: str | None = None,
) -> None:
    adapter_events = await ui_data_provider.list_adapter_events(interaction.channel_id)
    language = await language_for_interaction(interaction, ui_data_provider, localizer)
    if not adapter_events:
        await send_initial_result(
            interaction,
            reply_result(localizer, language, "discord.reply_ui.errors.no_event_triggers"),
        )
        return
    await interaction.response.send_modal(
        EventReplyAddModal(
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            adapter_events=adapter_events,
            localizer=localizer,
            language=language,
            default_event_id=default_event_id,
            default_message=default_message,
        )
    )


async def language_for_interaction(
    interaction: discord.Interaction,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> str:
    return localizer.resolve_language(await ui_data_provider.get_thread_language(interaction.channel_id))


def localized_reply_action_title(
    localizer: Localizer,
    language: str,
    action: str,
) -> str:
    return localizer.text(
        f"discord.reply_ui.action.{action}_title",
        language=language,
    )


def reply_result(
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
