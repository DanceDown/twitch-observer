"""Typed dispatch helpers for reply commands."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import (
    AddChannelEventReplyCommand,
    AddPatternReplyCommand,
    RemoveChannelEventReplyCommand,
    RemovePatternReplyCommand,
    SetChannelEventReplyEnabledCommand,
    SetPatternReplyEnabledCommand,
)
from src.events.discord_results import DiscordCommandResult


async def dispatch_add_pattern_reply(
    services: DiscordServiceBundle,
    command: AddPatternReplyCommand,
) -> DiscordCommandResult:
    """Dispatch a pattern auto-reply creation command to the service layer."""
    return await services.reply.handle_add_pattern_command(command)


async def dispatch_remove_pattern_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> DiscordCommandResult:
    """Dispatch removal of the auto-reply attached to one pattern."""
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
) -> DiscordCommandResult:
    """Dispatch enabling the auto-reply attached to one pattern."""
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
) -> DiscordCommandResult:
    """Dispatch disabling the auto-reply attached to one pattern."""
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
    command: AddChannelEventReplyCommand,
) -> DiscordCommandResult:
    """Dispatch creation of a live/offline event auto-reply action."""
    return await services.reply.handle_add_event_command(command)


async def dispatch_remove_channel_event_reply(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    adapter_event_id: int,
) -> DiscordCommandResult:
    """Dispatch removal of a live/offline event auto-reply action."""
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
) -> DiscordCommandResult:
    """Dispatch enabling a live/offline event auto-reply action."""
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
) -> DiscordCommandResult:
    """Dispatch disabling a live/offline event auto-reply action."""
    return await services.reply.handle_set_event_enabled_command(
        SetChannelEventReplyEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
            enabled=False,
        ),
    )
