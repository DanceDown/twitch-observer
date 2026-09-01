"""Typed dispatch helpers for tracked-channel commands."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import AddTrackedChannelCommand, RemoveTrackedChannelCommand, SetTrackedChannelColorCommand
from src.events.discord_results import DiscordCommandResult


async def dispatch_add_tracked_channel(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_login: str,
) -> DiscordCommandResult:
    """Dispatch a request to start tracking a Twitch channel."""
    return await services.channel.handle_add(
        AddTrackedChannelCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
        ),
    )


async def dispatch_remove_tracked_channel(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_login: str,
) -> DiscordCommandResult:
    """Dispatch a request to stop tracking a Twitch channel."""
    return await services.channel.handle_remove(
        RemoveTrackedChannelCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
        ),
    )


async def dispatch_set_tracked_channel_color(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_login: str,
    color: str | None,
) -> DiscordCommandResult:
    """Dispatch a request to set or clear a tracked channel color."""
    return await services.channel.handle_color(
        SetTrackedChannelColorCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
            color=color,
        ),
    )
