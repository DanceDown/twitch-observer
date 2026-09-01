"""Typed dispatch helpers for manual Twitch writes."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import SendTwitchMessageCommand
from src.events.discord_results import DiscordCommandResult


async def dispatch_send_twitch_message(
    services: DiscordServiceBundle,
    command: SendTwitchMessageCommand,
) -> DiscordCommandResult:
    """Dispatch a manual Twitch chat write request."""
    return await services.write.handle_request(command)
