"""Typed dispatch helpers for pattern commands."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import AddPatternCommand, EditPatternCommand, RemovePatternCommand, SetPatternEnabledCommand
from src.events.discord_results import DiscordCommandResult


async def dispatch_add_pattern(
    services: DiscordServiceBundle,
    command: AddPatternCommand,
) -> DiscordCommandResult:
    """Dispatch creation of a Twitch chat ping pattern."""
    return await services.pattern.handle_add_command(command)


async def dispatch_remove_pattern(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> DiscordCommandResult:
    """Dispatch removal of a Twitch chat ping pattern."""
    return await services.pattern.handle_remove_command(
        RemovePatternCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
        ),
    )


async def dispatch_enable_pattern(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> DiscordCommandResult:
    """Dispatch enabling of a Twitch chat ping pattern."""
    return await services.pattern.handle_set_enabled_command(
        SetPatternEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
            enabled=True,
        ),
    )


async def dispatch_disable_pattern(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> DiscordCommandResult:
    """Dispatch disabling of a Twitch chat ping pattern."""
    return await services.pattern.handle_set_enabled_command(
        SetPatternEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
            enabled=False,
        ),
    )


async def dispatch_edit_pattern(
    services: DiscordServiceBundle,
    command: EditPatternCommand,
) -> DiscordCommandResult:
    """Dispatch editing of an existing Twitch chat ping pattern."""
    return await services.pattern.handle_edit_command(command)
