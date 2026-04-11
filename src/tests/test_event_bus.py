from __future__ import annotations

import pytest

from src.events.event_bus import EventBus
from src.events.event_types import EventType, TwitchChatMessageEvent


@pytest.mark.asyncio
async def test_event_bus_invokes_sync_and_async_handlers() -> None:
    bus = EventBus()
    calls: list[str] = []

    def sync_handler(event: TwitchChatMessageEvent) -> None:
        calls.append(f"sync:{event.channel_login}")

    async def async_handler(event: TwitchChatMessageEvent) -> None:
        calls.append(f"async:{event.author_login}")

    bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, sync_handler)
    bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, async_handler)

    await bus.publish(
        EventType.TWITCH_CHAT_MESSAGE,
        TwitchChatMessageEvent(channel_login="test", author_login="alice", content="hello"),
    )

    assert calls == ["sync:test", "async:alice"]
