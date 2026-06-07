from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from random import seed
from contextlib import asynccontextmanager

import pytest

from src.database.connection import MessageRepository, RecentMessageRecord, ThreadRecord
from src.database.postgres import PostgresMessageRepository
from src.events.twitch_events import TwitchChatMessageEvent
from src.services.discord_ui_queries import WriteQueryService
from src.services.discord_presence_service import DiscordPresenceService, DiscordPresenceStatusSender
from src.services.message_ingest_service import MessageIngestService


@dataclass
class InMemoryMessageRepository(MessageRepository):
    messages: list[TwitchChatMessageEvent] = field(default_factory=list)
    matched_by_thread_id: dict[int, list[str]] = field(default_factory=dict)

    async def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        self.messages.append(event)

    async def list_recent_messages(self, *, since: datetime, limit: int) -> list[RecentMessageRecord]:
        rows = [
            RecentMessageRecord(
                message_id=_require_message_id(message),
                twitch_channel_id=message.broadcaster_id or message.channel_login,
                username=message.author_display_name or message.author_login,
                content=message.content,
                timestamp=message.sent_at,
            )
            for message in self.messages
            if message.sent_at >= since
        ]
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
        thread_matches = self.matched_by_thread_id.setdefault(thread_id, [])
        if message_id not in thread_matches:
            thread_matches.append(message_id)

    async def list_recent_messages_for_thread(
        self,
        *,
        thread_id: int,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        matched_message_ids = set(self.matched_by_thread_id.get(thread_id, []))
        rows = [
            row
            for row in await self.list_recent_messages(since=since, limit=max(limit * 10, limit))
            if row.message_id in matched_message_ids
        ]
        return rows[:limit]


@dataclass
class StaticThreadRepository:
    thread: ThreadRecord | None

    async def get_by_discord_channel_id(self, _discord_channel_id: int) -> ThreadRecord | None:
        return self.thread


@dataclass
class FakePresenceNotifier(DiscordPresenceStatusSender):
    statuses: list[str] = field(default_factory=list)

    async def set_status_text(self, text: str) -> None:
        self.statuses.append(text)


@dataclass
class RecordingCursor:
    statements: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    async def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.statements.append((query, params))


@dataclass
class RecordingDatabase:
    cursor_instance: RecordingCursor = field(default_factory=RecordingCursor)

    @asynccontextmanager
    async def async_cursor(self) -> RecordingCursor:
        yield self.cursor_instance


@pytest.mark.asyncio
async def test_message_ingest_service_registers_and_persists_messages() -> None:
    repository = InMemoryMessageRepository()
    service = MessageIngestService(message_repository=repository)

    event = TwitchChatMessageEvent(channel_login="channel", author_login="bob", content="hey")
    await service.handle_chat_message(event)

    assert repository.messages == [event]
    assert service.handled_messages == 1


@pytest.mark.asyncio
async def test_presence_service_uses_recent_message_as_status() -> None:
    repository = InMemoryMessageRepository()
    ingest_service = MessageIngestService(message_repository=repository)
    notifier = FakePresenceNotifier()
    service = DiscordPresenceService(
        message_repository=repository,
        notifier=notifier,
        poll_interval_seconds=60,
        lookback_minutes=5,
        message_limit=50,
        max_status_length=120,
    )

    event = TwitchChatMessageEvent(
        channel_login="channel",
        author_login="bob",
        author_display_name="Bob",
        content="A tracked message",
        message_id="presence-1",
    )

    await ingest_service.handle_chat_message(event)
    seed(1)
    await service.poll_once()

    assert notifier.statuses
    assert notifier.statuses[-1] == '"A tracked message" ~Bob'


@pytest.mark.asyncio
async def test_presence_service_keeps_current_status_when_no_recent_message_exists() -> None:
    repository = InMemoryMessageRepository()
    notifier = FakePresenceNotifier(statuses=["old status"])
    service = DiscordPresenceService(
        message_repository=repository,
        notifier=notifier,
        poll_interval_seconds=60,
        lookback_minutes=5,
        message_limit=50,
        max_status_length=120,
    )

    await service.poll_once()

    assert notifier.statuses == ["old status"]


@pytest.mark.asyncio
async def test_postgres_message_repository_uses_null_reply_reference_when_parent_is_missing() -> None:
    database = RecordingDatabase()
    repository = PostgresMessageRepository(database=database)  # type: ignore[arg-type]
    event = TwitchChatMessageEvent(
        channel_login="channel",
        author_login="bob",
        author_display_name="Bob",
        author_id="user-1",
        broadcaster_id="channel-1",
        message_id="msg-1",
        reply_parent_message_id="missing-parent",
        content="reply body",
    )

    await repository.save_twitch_message(event)

    assert len(database.cursor_instance.statements) == 1
    query, params = database.cursor_instance.statements[0]

    assert query.upper().count("VALUES") == 1
    assert "SELECT message_id FROM message WHERE message_id = %s" in query
    assert params == (
        "msg-1",
        "channel-1",
        event.sent_at,
        "user-1",
        "Bob",
        "reply body",
        "missing-parent",
    )


@pytest.mark.asyncio
async def test_postgres_message_repository_requires_message_id() -> None:
    database = RecordingDatabase()
    repository = PostgresMessageRepository(database=database)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="missing message_id"):
        await repository.save_twitch_message(
            TwitchChatMessageEvent(
                channel_login="channel",
                author_login="bob",
                author_display_name="Bob",
                author_id="user-1",
                broadcaster_id="channel-1",
                message_id=None,
                content="reply body",
            )
        )


@pytest.mark.asyncio
async def test_write_query_service_only_returns_messages_matched_in_thread() -> None:
    repository = InMemoryMessageRepository()
    ingest_service = MessageIngestService(message_repository=repository)
    query_service = WriteQueryService(
        thread_repository=StaticThreadRepository(
            ThreadRecord(
                thread_id=7,
                owner_id=1,
                discord_channel_id=42,
                enabled=True,
                color=None,
                language="german",
            )
        ),
        message_repository=repository,
    )

    matched_event = TwitchChatMessageEvent(
        channel_login="chan-a",
        author_login="alice",
        author_display_name="Alice",
        broadcaster_id="channel-a",
        message_id="msg-matched",
        content="matched text",
    )
    unrelated_event = TwitchChatMessageEvent(
        channel_login="chan-b",
        author_login="bob",
        author_display_name="Bob",
        broadcaster_id="channel-b",
        message_id="msg-unrelated",
        content="unrelated text",
    )

    await ingest_service.handle_chat_message(matched_event)
    await ingest_service.handle_chat_message(unrelated_event)
    await repository.mark_message_matched_in_thread(thread_id=7, event=matched_event)

    candidates = await query_service.list_recent_reply_candidates(
        discord_channel_id=42,
        max_age_minutes=5,
        limit=10,
    )

    assert [candidate.message_id for candidate in candidates] == ["msg-matched"]


def _require_message_id(event: TwitchChatMessageEvent) -> str:
    assert event.message_id is not None
    return event.message_id
