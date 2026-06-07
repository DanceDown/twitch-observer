"""Business services reacting to domain events."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import MessageRepository
from src.events.twitch_events import TwitchChatMessageEvent


@dataclass(slots=True)
class MessageIngestService:
    """Persist incoming Twitch chat messages.

    This is the first concrete step in the chat pipeline:
    entrypoint -> pipeline step -> repository/database
    """

    message_repository: MessageRepository
    handled_messages: int = field(default=0, init=False)

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Store an incoming message and track processing metrics."""
        await self.message_repository.save_twitch_message(event)
        self.handled_messages += 1
