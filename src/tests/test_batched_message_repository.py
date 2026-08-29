from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from src.database.connection import MessageRepository, RecentMessageRecord
from src.errors import DatabasePoolExhaustedError
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


@dataclass
class FailingBatchMessageRepository(FakeBatchMessageRepository):
    error: psycopg.Error = field(
        default_factory=lambda: psycopg.OperationalError("consuming input failed: server closed the connection unexpectedly")
    )
    flush_attempts: int = 0

    async def flush_write_batch(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None:
        _ = message_events, thread_matches
        self.flush_attempts += 1
        raise self.error


@dataclass
class PoolExhaustedBatchMessageRepository(FakeBatchMessageRepository):
    flush_attempts: int = 0

    async def flush_write_batch(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None:
        _ = message_events, thread_matches
        self.flush_attempts += 1
        raise DatabasePoolExhaustedError("pool exhausted")


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
async def test_batched_message_repository_defers_full_batch_flush_when_worker_is_running() -> None:
    inner = FakeBatchMessageRepository()
    repository = BatchedMessageRepository(repository=inner, batch_size=2, flush_interval_seconds=60)

    await repository.start()
    await repository.save_twitch_message(_event("msg-3"))
    await repository.save_twitch_message(_event("msg-4"))

    assert inner.flush_batches == []

    await repository.stop()
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


@pytest.mark.asyncio
async def test_batched_message_repository_stop_logs_transient_postgres_disconnect_as_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    inner = FailingBatchMessageRepository()
    spool_path = tmp_path / "message-spool.json"
    repository = BatchedMessageRepository(repository=inner, batch_size=50, flush_interval_seconds=60, spool_path=str(spool_path))

    await repository.save_twitch_message(_event("msg-db-down"))

    with caplog.at_level(logging.WARNING):
        await repository.stop()

    assert inner.flush_attempts == 1
    assert "Final batched message write flush skipped during shutdown" in caplog.text
    assert "pending writes were spooled" in caplog.text
    assert spool_path.exists()
    assert repository._pending_messages.keys() == {"msg-db-down"}
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_batched_message_repository_replays_spooled_shutdown_writes_on_start(tmp_path: Path) -> None:
    spool_path = tmp_path / "message-spool.json"
    failing_inner = FailingBatchMessageRepository()
    failing_repository = BatchedMessageRepository(
        repository=failing_inner,
        batch_size=50,
        flush_interval_seconds=60,
        spool_path=str(spool_path),
    )
    event = _event("msg-spooled")

    await failing_repository.save_twitch_message(event)
    await failing_repository.mark_message_matched_in_thread(thread_id=7, event=event)
    await failing_repository.stop()

    payload = json.loads(spool_path.read_text(encoding="utf-8"))
    assert [item["message_id"] for item in payload["messages"]] == ["msg-spooled"]
    assert [item["event"]["message_id"] for item in payload["thread_matches"]] == ["msg-spooled"]

    recovered_inner = FakeBatchMessageRepository()
    recovered_repository = BatchedMessageRepository(
        repository=recovered_inner,
        batch_size=50,
        flush_interval_seconds=60,
        spool_path=str(spool_path),
    )

    await recovered_repository.start()
    await recovered_repository.stop()

    assert recovered_inner.flush_batches == [(("msg-spooled",), ((7, "msg-spooled"),))]
    assert not spool_path.exists()


@pytest.mark.asyncio
async def test_batched_message_repository_spools_pending_writes_when_pool_is_exhausted_on_stop(tmp_path: Path) -> None:
    inner = PoolExhaustedBatchMessageRepository()
    spool_path = tmp_path / "message-spool.json"
    repository = BatchedMessageRepository(repository=inner, batch_size=50, flush_interval_seconds=60, spool_path=str(spool_path))

    await repository.save_twitch_message(_event("msg-pool-down"))
    await repository.stop()

    assert inner.flush_attempts == 1
    assert spool_path.exists()


@pytest.mark.asyncio
async def test_batched_message_repository_background_requeues_transient_postgres_disconnect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    inner = FailingBatchMessageRepository()
    repository = BatchedMessageRepository(repository=inner, batch_size=50, flush_interval_seconds=0.01)

    await repository.start()
    with caplog.at_level(logging.WARNING):
        await repository.save_twitch_message(_event("msg-retry"))
        await asyncio.sleep(0.03)
        await repository.stop()

    assert inner.flush_attempts >= 1
    assert "pending writes were requeued" in caplog.text
    assert repository._pending_messages.keys() == {"msg-retry"}
    assert all(record.exc_info is None for record in caplog.records)


def _require_message_id(event: TwitchChatMessageEvent) -> str:
    assert event.message_id is not None
    return event.message_id
