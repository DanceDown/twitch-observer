from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import MessageRepository
from src.events.event_bus import EventBus
from src.events.event_types import EventType, TwitchChatMessageEvent
from src.services.message_ingest_service import MessageIngestService


@dataclass
class InMemoryMessageRepository(MessageRepository):
    messages: list[TwitchChatMessageEvent] = field(default_factory=list)

    def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        self.messages.append(event)


def test_message_ingest_service_registers_and_persists_messages() -> None:
    bus = EventBus()
    repository = InMemoryMessageRepository()
    service = MessageIngestService(event_bus=bus, message_repository=repository)

    event = TwitchChatMessageEvent(channel_login="channel", author_login="bob", content="hey")
    import asyncio

    asyncio.run(bus.publish(EventType.TWITCH_CHAT_MESSAGE, event))

    assert repository.messages == [event]
    assert service.handled_messages == 1
