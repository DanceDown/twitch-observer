"""Twitch chat-write workflows split from user-directory lookup responsibilities."""

from __future__ import annotations

from dataclasses import dataclass

from src.events.twitch_events import TwitchChatSendRequest
from src.gateways.twitch_api import TwitchAPIClient


@dataclass(slots=True)
class TwitchChatWriteService:
    """Send Twitch chat messages and replies."""

    twitch_api: TwitchAPIClient

    async def send_chat_message(self, request: TwitchChatSendRequest) -> str:
        """Send one Twitch chat message through the API gateway."""
        return await self.twitch_api.send_chat_message(request)
