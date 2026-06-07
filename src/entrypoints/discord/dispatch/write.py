"""Typed dispatch helpers for manual Twitch writes."""

from __future__ import annotations

from src.events.commands import SendTwitchMessageCommand
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_send_twitch_message(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_login: str,
    message: str,
    reply_parent_message_id: str | None,
) -> object:
    return await services.write.handle_request(
        SendTwitchMessageCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
            message=message,
            reply_parent_message_id=reply_parent_message_id,
        ),
    )
