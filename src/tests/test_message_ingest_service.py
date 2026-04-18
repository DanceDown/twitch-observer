from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from random import seed

from src.database.connection import MessageRepository, RecentMessageRecord
from src.events.event_bus import EventBus
from src.events.event_types import EventType, TwitchChatMessageEvent
from src.services.discord_presence_service import DiscordPresenceService, DiscordPresenceStatusSender
from src.services.message_ingest_service import MessageIngestService


@dataclass
class InMemoryMessageRepository(MessageRepository):
    messages: list[TwitchChatMessageEvent] = field(default_factory=list)

    def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        self.messages.append(event)

    def list_recent_messages(self, *, since: datetime, limit: int) -> list[RecentMessageRecord]:
        rows = [
            RecentMessageRecord(
                username=message.author_display_name or message.author_login,
                content=message.content,
                timestamp=message.sent_at,
            )
            for message in self.messages
            if message.sent_at >= since
        ]
        rows.sort(key=lambda row: row.timestamp, reverse=True)
        return rows[:limit]


@dataclass
class FakePresenceNotifier(DiscordPresenceStatusSender):
    statuses: list[str] = field(default_factory=list)

    async def set_status_text(self, text: str) -> None:
        self.statuses.append(text)


def test_message_ingest_service_registers_and_persists_messages() -> None:
    bus = EventBus()
    repository = InMemoryMessageRepository()
    service = MessageIngestService(event_bus=bus, message_repository=repository)

    event = TwitchChatMessageEvent(channel_login="channel", author_login="bob", content="hey")
    import asyncio

    asyncio.run(bus.publish(EventType.TWITCH_CHAT_MESSAGE, event))

    assert repository.messages == [event]
    assert service.handled_messages == 1


def test_presence_service_uses_recent_message_as_status() -> None:
    bus = EventBus()
    repository = InMemoryMessageRepository()
    MessageIngestService(event_bus=bus, message_repository=repository)
    notifier = FakePresenceNotifier()
    service = DiscordPresenceService(message_repository=repository, notifier=notifier)

    event = TwitchChatMessageEvent(channel_login="channel", author_login="bob", author_display_name="Bob", content="A tracked message")
    import asyncio

    asyncio.run(bus.publish(EventType.TWITCH_CHAT_MESSAGE, event))
    seed(1)
    asyncio.run(service.poll_once())

    assert notifier.statuses
    assert notifier.statuses[-1] == "\"A tracked message\" ~Bob"


def test_presence_service_keeps_current_status_when_no_recent_message_exists() -> None:
    repository = InMemoryMessageRepository()
    notifier = FakePresenceNotifier(statuses=["old status"])
    service = DiscordPresenceService(message_repository=repository, notifier=notifier)

    import asyncio

    asyncio.run(service.poll_once())

    assert notifier.statuses == ["old status"]
