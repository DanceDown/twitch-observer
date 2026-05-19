"""Twitch chat-write workflows split from user-directory lookup responsibilities."""

from __future__ import annotations

from dataclasses import dataclass

from src.gateways.twitch_api import TwitchAPIClient


@dataclass(slots=True)
class TwitchChatWriteService:
    """Send Twitch chat messages and replies."""

    twitch_api: TwitchAPIClient

    async def send_chat_message(
        self,
        *,
        access_token: str,
        client_id: str,
        sender_id: str,
        broadcaster_id: str,
        message: str,
        reply_parent_message_id: str | None = None,
    ) -> str:
        return await self.twitch_api.send_chat_message(
            access_token=access_token,
            client_id=client_id,
            sender_id=sender_id,
            broadcaster_id=broadcaster_id,
            message=message,
            reply_parent_message_id=reply_parent_message_id,
        )
