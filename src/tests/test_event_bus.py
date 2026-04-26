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


@pytest.mark.asyncio
async def test_event_bus_logs_failed_handler_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus()
    calls: list[str] = []

    def failing_handler(event: TwitchChatMessageEvent) -> None:
        raise RuntimeError("boom")

    async def next_handler(event: TwitchChatMessageEvent) -> None:
        calls.append(event.content)

    bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, failing_handler)
    bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, next_handler)

    await bus.publish(
        EventType.TWITCH_CHAT_MESSAGE,
        TwitchChatMessageEvent(channel_login="test", author_login="alice", content="hello"),
    )

    assert calls == ["hello"]
    assert "Subscriber failing_handler failed while handling event twitch.chat.message" in caplog.text
