"""Typed dispatch helpers for thread/context commands."""

from __future__ import annotations

from src.events.event_types import (
    JoinThreadCommand,
    LeaveThreadCommand,
    SetThreadColorCommand,
    SetThreadEnabledCommand,
    SetThreadLanguageCommand,
)
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_join_thread(services: DiscordServiceBundle, *, discord_channel_id: int, requester_id: int) -> object:
    return await services.thread.handle_join(JoinThreadCommand(discord_channel_id=discord_channel_id, requester_id=requester_id))


async def dispatch_leave_thread(services: DiscordServiceBundle, *, discord_channel_id: int, requester_id: int) -> object:
    return await services.thread.handle_leave(LeaveThreadCommand(discord_channel_id=discord_channel_id, requester_id=requester_id))


async def dispatch_enable_thread(services: DiscordServiceBundle, *, discord_channel_id: int, requester_id: int) -> object:
    return await services.thread.handle_set_enabled(
        SetThreadEnabledCommand(discord_channel_id=discord_channel_id, requester_id=requester_id, enabled=True)
    )


async def dispatch_disable_thread(services: DiscordServiceBundle, *, discord_channel_id: int, requester_id: int) -> object:
    return await services.thread.handle_set_enabled(
        SetThreadEnabledCommand(discord_channel_id=discord_channel_id, requester_id=requester_id, enabled=False)
    )


async def dispatch_set_thread_color(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    color: str | None,
) -> object:
    return await services.thread.handle_set_color(
        SetThreadColorCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            color=color,
        )
    )


async def dispatch_set_thread_language(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    language: str,
) -> object:
    return await services.thread.handle_set_language(
        SetThreadLanguageCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            language=language,
        )
    )
