"""Typed dispatch helpers for tracked-channel commands."""

from __future__ import annotations

from src.events.event_types import AddTrackedChannelCommand, RemoveTrackedChannelCommand, SetTrackedChannelColorCommand
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_add_tracked_channel(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_login: str,
) -> object:
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
) -> object:
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
) -> object:
    return await services.channel.handle_color(
        SetTrackedChannelColorCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
            color=color,
        ),
    )
