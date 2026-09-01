"""Typed dispatch helpers for Discord permission commands."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import ClearPermissionsCommand, GrantPermissionsCommand, RevokePermissionsCommand
from src.events.discord_results import DiscordCommandResult


async def dispatch_grant_permissions(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    target_user_id: int,
    permissions: tuple[str, ...],
) -> DiscordCommandResult:
    """Dispatch a request to grant Discord-context permissions."""
    return await services.permission.handle_grant(
        GrantPermissionsCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            target_user_id=target_user_id,
            permissions=permissions,
        ),
    )


async def dispatch_revoke_permissions(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    target_user_id: int,
    permissions: tuple[str, ...],
) -> DiscordCommandResult:
    """Dispatch a request to revoke Discord-context permissions."""
    return await services.permission.handle_revoke(
        RevokePermissionsCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            target_user_id=target_user_id,
            permissions=permissions,
        ),
    )


async def dispatch_clear_permissions(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    target_user_id: int,
) -> DiscordCommandResult:
    """Dispatch a request to clear Discord-context permissions."""
    return await services.permission.handle_clear(
        ClearPermissionsCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            target_user_id=target_user_id,
        ),
    )
