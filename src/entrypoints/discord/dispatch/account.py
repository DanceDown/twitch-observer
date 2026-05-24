"""Typed dispatch helpers for Twitch account commands."""

from __future__ import annotations

from src.events.event_types import StartAccountLinkCommand, UnlinkAccountCommand
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_start_account_link(
    services: DiscordServiceBundle,
    *,
    requester_id: int,
    discord_channel_id: int | None,
) -> object:
    return await services.account.handle_link_command(
        StartAccountLinkCommand(
            requester_id=requester_id,
            discord_channel_id=discord_channel_id,
        ),
    )


async def dispatch_unlink_account(
    services: DiscordServiceBundle,
    *,
    requester_id: int,
    discord_channel_id: int | None,
) -> object:
    return await services.account.handle_unlink_command(
        UnlinkAccountCommand(
            requester_id=requester_id,
            discord_channel_id=discord_channel_id,
        ),
    )
