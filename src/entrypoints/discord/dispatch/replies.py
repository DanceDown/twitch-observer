"""Typed dispatch helpers for reply commands."""

from __future__ import annotations

from src.events.event_types import (
    AddChannelEventReplyCommand,
    AddPatternReplyCommand,
    RemoveChannelEventReplyCommand,
    RemovePatternReplyCommand,
    SetChannelEventReplyEnabledCommand,
    SetPatternReplyEnabledCommand,
)
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_add_pattern_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
    message: str,
    reply_as_reply: bool,
) -> object:
    return await services.reply.handle_add_pattern_command(
        AddPatternReplyCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
            message=message,
            reply_as_reply=reply_as_reply,
        ),
    )


async def dispatch_remove_pattern_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> object:
    return await services.reply.handle_remove_pattern_command(
        RemovePatternReplyCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
        ),
    )


async def dispatch_enable_pattern_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> object:
    return await services.reply.handle_set_pattern_enabled_command(
        SetPatternReplyEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
            enabled=True,
        ),
    )


async def dispatch_disable_pattern_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> object:
    return await services.reply.handle_set_pattern_enabled_command(
        SetPatternReplyEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
            enabled=False,
        ),
    )


async def dispatch_add_channel_event_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    adapter_event_id: int,
    message: str,
    reply_as_reply: bool,
) -> object:
    return await services.reply.handle_add_event_command(
        AddChannelEventReplyCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
            message=message,
            reply_as_reply=reply_as_reply,
        ),
    )


async def dispatch_remove_channel_event_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    adapter_event_id: int,
) -> object:
    return await services.reply.handle_remove_event_command(
        RemoveChannelEventReplyCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
        ),
    )


async def dispatch_enable_channel_event_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    adapter_event_id: int,
) -> object:
    return await services.reply.handle_set_event_enabled_command(
        SetChannelEventReplyEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
            enabled=True,
        ),
    )


async def dispatch_disable_channel_event_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    adapter_event_id: int,
) -> object:
    return await services.reply.handle_set_event_enabled_command(
        SetChannelEventReplyEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
            enabled=False,
        ),
    )
