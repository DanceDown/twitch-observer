"""Typed dispatch helpers for configuration overview commands."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import ShowConfigurationCommand
from src.events.discord_results import DiscordCommandResult


async def dispatch_show_configuration(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    sections: tuple[str, ...],
) -> DiscordCommandResult:
    """Dispatch a request to show context configuration."""
    return await services.show.handle_command(
        ShowConfigurationCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            sections=sections,
        ),
    )
