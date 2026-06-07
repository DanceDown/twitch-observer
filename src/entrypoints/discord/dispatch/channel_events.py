"""Typed dispatch helpers for tracked live/offline event commands."""

from __future__ import annotations

from src.events.commands import AddChannelEventCommand, RemoveChannelEventCommand, SetChannelEventColorCommand
from src.events.twitch_events import StreamEventKind
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_add_channel_event(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_id: str,
    event_kind: StreamEventKind,
) -> object:
    return await services.channel_event.handle_add_command(
        AddChannelEventCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_id=twitch_channel_id,
            event_kind=event_kind,
        ),
    )


async def dispatch_remove_channel_event(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_id: str,
    event_kind: StreamEventKind,
) -> object:
    return await services.channel_event.handle_remove_command(
        RemoveChannelEventCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_id=twitch_channel_id,
            event_kind=event_kind,
        ),
    )


async def dispatch_set_channel_event_color(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_id: str,
    event_kind: StreamEventKind,
    color: str | None,
) -> object:
    return await services.channel_event.handle_set_color_command(
        SetChannelEventColorCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_id=twitch_channel_id,
            event_kind=event_kind,
            color=color,
        ),
    )
