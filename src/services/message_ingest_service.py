from __future__ import annotations

"""Business services reacting to domain events."""

from dataclasses import dataclass, field

from src.database.connection import MessageRepository
from src.events.event_bus import EventBus
from src.events.event_types import EventType, TwitchChatMessageEvent


@dataclass(slots=True)
class MessageIngestService:
    """Persist incoming Twitch chat messages.

    This is the first concrete example of the intended architecture:
    adapter -> event bus -> service -> repository/database
    """

    event_bus: EventBus
    message_repository: MessageRepository
    handled_messages: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Subscribe the service to Twitch chat events."""
        self.event_bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, self.handle_chat_message)

    def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Store an incoming message and track processing metrics."""
        self.message_repository.save_twitch_message(event)
        self.handled_messages += 1
