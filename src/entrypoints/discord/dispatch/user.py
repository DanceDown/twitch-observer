"""Typed dispatch helpers for tracked-user commands."""

from __future__ import annotations

from src.events.event_types import AddTrackedUserCommand, RemoveTrackedUserCommand
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_add_tracked_user(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_user_login: str,
) -> object:
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
) -> object:
    return await services.user.handle_remove(
        RemoveTrackedUserCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_user_login=twitch_user_login,
        ),
    )
