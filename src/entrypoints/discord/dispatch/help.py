"""Typed dispatch helpers for beginner-friendly help output."""

from __future__ import annotations

from src.events.commands import HelpCommand
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_help(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int | None,
    requester_id: int,
    language_hint: str | None,
    section: str | None,
) -> object:
    return await services.help.handle_command(
        HelpCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            language_hint=language_hint,
            section=section,
        ),
    )
