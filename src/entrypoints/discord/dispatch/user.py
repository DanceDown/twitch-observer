"""Typed dispatch helpers for tracked-user commands."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import AddTrackedUserCommand, RemoveTrackedUserCommand
from src.events.discord_results import DiscordCommandResult


async def dispatch_add_tracked_user(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_user_login: str,
) -> DiscordCommandResult:
    """Dispatch a request to add a tracked Twitch user."""
    return await services.user.handle_add(
        AddTrackedUserCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_user_login=twitch_user_login,
        ),
    )


async def dispatch_remove_tracked_user(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_user_login: str,
) -> DiscordCommandResult:
    """Dispatch a request to remove a tracked Twitch user."""
    return await services.user.handle_remove(
        RemoveTrackedUserCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_user_login=twitch_user_login,
        ),
    )
