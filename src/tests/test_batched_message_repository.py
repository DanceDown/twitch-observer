from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.database.connection import MessageRepository, RecentMessageRecord
from src.events.twitch_events import TwitchChatMessageEvent
from src.services.batched_message_repository import BatchedMessageRepository


@dataclass
class FakeBatchMessageRepository(MessageRepository):
    recent_messages: dict[str, RecentMessageRecord] = field(default_factory=dict)
    matched_by_thread_id: dict[int, list[str]] = field(default_factory=dict)
    flush_batches: list[tuple[tuple[str, ...], tuple[tuple[int, str], ...]]] = field(default_factory=list)
    saved_bot_message_ids: list[str] = field(default_factory=list)

    async def flush_write_batch(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None:
        message_ids = []
        match_ids = []
        for event in message_events:
            message_id = _require_message_id(event)
            message_ids.append(message_id)
            self.recent_messages[message_id] = RecentMessageRecord(
                message_id=message_id,
                twitch_channel_id=event.broadcaster_id or event.channel_login,
                username=event.author_display_name or event.author_login,
                content=event.content,
                timestamp=event.sent_at,
            )
        for thread_id, event in thread_matches:
            message_id = _require_message_id(event)
            match_ids.append((thread_id, message_id))
            thread_matches_for_id = self.matched_by_thread_id.setdefault(thread_id, [])
            if message_id not in thread_matches_for_id:
                thread_matches_for_id.append(message_id)
        self.flush_batches.append((tuple(message_ids), tuple(match_ids)))

    async def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        message_id = _require_message_id(event)
        self.recent_messages[message_id] = RecentMessageRecord(
            message_id=message_id,
            twitch_channel_id=event.broadcaster_id or event.channel_login,
            username=event.author_display_name or event.author_login,
            content=event.content,
            timestamp=event.sent_at,
        )

    async def save_bot_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        message_id = _require_message_id(event)
        self.saved_bot_message_ids.append(message_id)
        await self.save_twitch_message(event)

    async def list_recent_messages(self, *, since: datetime, limit: int) -> list[RecentMessageRecord]:
        rows = [row for row in self.recent_messages.values() if row.timestamp >= since]
        rows.sort(key=lambda row: row.timestamp, reverse=True)
        return rows[:limit]

    async def list_recent_messages_for_channel(
        self,
        *,
        twitch_channel_id: str,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        rows = [
            row
            for row in await self.list_recent_messages(since=since, limit=max(limit * 5, limit))
            if row.twitch_channel_id == twitch_channel_id
        ]
        return rows[:limit]

    async def mark_message_matched_in_thread(
        self,
        *,
        thread_id: int,
        event: TwitchChatMessageEvent,
    ) -> None:
        message_id = _require_message_id(event)
        self.matched_by_thread_id.setdefault(thread_id, []).append(message_id)

    async def list_recent_messages_for_thread(
        self,
        *,
        thread_id: int,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        matched_ids = set(self.matched_by_thread_id.get(thread_id, []))
        rows = [row for row in await self.list_recent_messages(since=since, limit=max(limit * 10, limit)) if row.message_id in matched_ids]
        return rows[:limit]

    async def get_thread_message(
        self,
        *,
        thread_id: int,
        message_id: str,
    ) -> RecentMessageRecord | None:
        if message_id not in set(self.matched_by_thread_id.get(thread_id, [])):
            return None
        return self.recent_messages.get(message_id)


def _event(message_id: str | None, *, content: str = "hello", minutes_ago: int = 0) -> TwitchChatMessageEvent:
    return TwitchChatMessageEvent(
        channel_login="example",
        author_login="alice",
        author_display_name="Alice",
        broadcaster_id="channel-1",
        message_id=message_id,
        content=content,
        sent_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_batched_message_repository_flushes_pending_writes_before_read() -> None:
    inner = FakeBatchMessageRepository()
    repository = BatchedMessageRepository(repository=inner, batch_size=50, flush_interval_seconds=60)
    event = _event("msg-1")

    await repository.save_twitch_message(event)
    await repository.mark_message_matched_in_thread(thread_id=7, event=event)

    rows = await repository.list_recent_messages_for_thread(
        thread_id=7,
        since=datetime.now(UTC) - timedelta(minutes=5),
        limit=10,
    )

    assert [row.message_id for row in rows] == ["msg-1"]
    assert inner.flush_batches == [(("msg-1",), ((7, "msg-1"),))]


@pytest.mark.asyncio
async def test_batched_message_repository_background_worker_flushes_without_read() -> None:
    inner = FakeBatchMessageRepository()
    repository = BatchedMessageRepository(repository=inner, batch_size=50, flush_interval_seconds=0.01)
    event = _event("msg-2")

    await repository.start()
    await repository.save_twitch_message(event)
    await repository.mark_message_matched_in_thread(thread_id=9, event=event)
    await asyncio.sleep(0.05)
    await repository.stop()

    assert inner.flush_batches == [(("msg-2",), ((9, "msg-2"),))]


@pytest.mark.asyncio
async def test_batched_message_repository_flushes_immediately_when_batch_is_full() -> None:
    inner = FakeBatchMessageRepository()
    repository = BatchedMessageRepository(repository=inner, batch_size=2, flush_interval_seconds=60)

    await repository.save_twitch_message(_event("msg-3"))
    await repository.save_twitch_message(_event("msg-4"))

    assert inner.flush_batches == [(("msg-3", "msg-4"), ())]


@pytest.mark.asyncio
async def test_batched_message_repository_flushes_pending_inbound_messages_before_bot_save() -> None:
    inner = FakeBatchMessageRepository()
    repository = BatchedMessageRepository(repository=inner, batch_size=50, flush_interval_seconds=60)

    await repository.save_twitch_message(_event("msg-5"))
    await repository.save_bot_twitch_message(_event("bot-msg-1", content="bot reply"))

    assert inner.flush_batches == [(("msg-5",), ())]
    assert inner.saved_bot_message_ids == ["bot-msg-1"]


@pytest.mark.asyncio
async def test_batched_message_repository_requires_message_id_before_queueing() -> None:
    repository = BatchedMessageRepository(repository=FakeBatchMessageRepository(), batch_size=50, flush_interval_seconds=60)

    with pytest.raises(ValueError, match="missing message_id"):
        await repository.save_twitch_message(_event(None))


def _require_message_id(event: TwitchChatMessageEvent) -> str:
    assert event.message_id is not None
    return event.message_id
