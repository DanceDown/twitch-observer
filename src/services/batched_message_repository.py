"""Batched write wrapper for hot-path Twitch chat message persistence."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import psycopg

from src.database.connection import MessageRepository, RecentMessageRecord
from src.errors import DatabasePoolExhaustedError
from src.events.twitch_events import TwitchChatMessageEvent

logger = logging.getLogger(__name__)


class _BatchMessageWriteRepository(Protocol):
    async def flush_write_batch(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None: ...


@dataclass(slots=True)
class BatchedMessageRepository(MessageRepository):
    """Batch hot-path message writes while keeping reads consistent."""

    repository: MessageRepository
    batch_size: int = 50
    flush_interval_seconds: float = 0.25
    _pending_messages: dict[str, TwitchChatMessageEvent] = field(default_factory=dict, init=False)
    _pending_matches: dict[tuple[int, str], tuple[int, TwitchChatMessageEvent]] = field(default_factory=dict, init=False)
    _queue_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _wake_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop(), name="message-write-batcher")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        had_task = self._task is not None
        if had_task:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        else:
            await self._flush_for_shutdown()

    async def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        should_flush_now = await self._enqueue_message(event)
        if should_flush_now and self._task is None:
            await self.flush()

    async def save_bot_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        await self.flush()
        await self.repository.save_bot_twitch_message(event)

    async def mark_message_matched_in_thread(
        self,
        *,
        thread_id: int,
        event: TwitchChatMessageEvent,
    ) -> None:
        should_flush_now = await self._enqueue_match(thread_id=thread_id, event=event)
        if should_flush_now and self._task is None:
            await self.flush()

    async def list_recent_messages(
        self,
        *,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        await self.flush()
        return await self.repository.list_recent_messages(since=since, limit=limit)

    async def list_recent_messages_for_channel(
        self,
        *,
        twitch_channel_id: str,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        await self.flush()
        return await self.repository.list_recent_messages_for_channel(
            twitch_channel_id=twitch_channel_id,
            since=since,
            limit=limit,
        )

    async def list_recent_messages_for_thread(
        self,
        *,
        thread_id: int,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        await self.flush()
        return await self.repository.list_recent_messages_for_thread(
            thread_id=thread_id,
            since=since,
            limit=limit,
        )

    async def get_thread_message(
        self,
        *,
        thread_id: int,
        message_id: str,
    ) -> RecentMessageRecord | None:
        await self.flush()
        return await self.repository.get_thread_message(
            thread_id=thread_id,
            message_id=message_id,
        )

    async def flush(self) -> None:
        async with self._flush_lock:
            while True:
                snapshot = await self._take_snapshot()
                if snapshot is None:
                    return
                message_events, thread_matches = snapshot
                try:
                    await self._flush_snapshot(message_events=message_events, thread_matches=thread_matches)
                except (DatabasePoolExhaustedError, psycopg.Error):
                    await self._requeue_snapshot(message_events=message_events, thread_matches=thread_matches)
                    raise

    async def _enqueue_message(self, event: TwitchChatMessageEvent) -> bool:
        async with self._queue_lock:
            self._pending_messages[self._resolve_message_id(event)] = event
            pending_count = len(self._pending_messages) + len(self._pending_matches)
            self._wake_event.set()
            return pending_count >= max(1, self.batch_size)

    async def _enqueue_match(self, *, thread_id: int, event: TwitchChatMessageEvent) -> bool:
        async with self._queue_lock:
            key = (thread_id, self._resolve_message_id(event))
            self._pending_matches[key] = (thread_id, event)
            pending_count = len(self._pending_messages) + len(self._pending_matches)
            self._wake_event.set()
            return pending_count >= max(1, self.batch_size)

    async def _take_snapshot(
        self,
    ) -> tuple[tuple[TwitchChatMessageEvent, ...], tuple[tuple[int, TwitchChatMessageEvent], ...]] | None:
        async with self._queue_lock:
            if not self._pending_messages and not self._pending_matches:
                self._wake_event.clear()
                return None
            message_events = tuple(self._pending_messages.values())
            thread_matches = tuple(self._pending_matches.values())
            self._pending_messages = {}
            self._pending_matches = {}
            if not self._pending_messages and not self._pending_matches:
                self._wake_event.clear()
            return message_events, thread_matches

    async def _requeue_snapshot(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None:
        async with self._queue_lock:
            for event in message_events:
                self._pending_messages.setdefault(self._resolve_message_id(event), event)
            for thread_id, event in thread_matches:
                self._pending_matches.setdefault((thread_id, self._resolve_message_id(event)), (thread_id, event))
            self._wake_event.set()

    async def _flush_snapshot(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None:
        batch_repository = self.repository if hasattr(self.repository, "flush_write_batch") else None
        if batch_repository is not None:
            await getattr(batch_repository, "flush_write_batch")(
                message_events=message_events,
                thread_matches=thread_matches,
            )

            return
        for event in message_events:
            await self.repository.save_twitch_message(event)
        for thread_id, event in thread_matches:
            await self.repository.mark_message_matched_in_thread(
                thread_id=thread_id,
                event=event,
            )

    async def _run_loop(self) -> None:
        while True:
            await self._wake_event.wait()
            if self._stop_event.is_set():
                break
            if self.flush_interval_seconds > 0:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.flush_interval_seconds)
                except TimeoutError:
                    pass
            if self._stop_event.is_set():
                break
            try:
                await self.flush()
            except DatabasePoolExhaustedError:
                logger.error("Batched message write flush failed because the database pool is exhausted.")
            except psycopg.Error as error:
                self._log_postgres_flush_error(error)
        await self._flush_for_shutdown()

    async def _flush_for_shutdown(self) -> None:
        try:
            await self.flush()
        except DatabasePoolExhaustedError:
            logger.warning("Final batched message write flush skipped during shutdown because the database pool is exhausted.")
        except psycopg.Error as error:
            if _is_transient_postgres_disconnect(error):
                logger.warning(
                    "Final batched message write flush skipped during shutdown because PostgreSQL is unavailable: %s",
                    _compact_error_message(error),
                )
                return
            logger.exception("Final batched message write flush failed during shutdown.")

    @staticmethod
    def _log_postgres_flush_error(error: psycopg.Error) -> None:
        if _is_transient_postgres_disconnect(error):
            logger.warning(
                "Batched message write flush failed because PostgreSQL is temporarily unavailable; pending writes were requeued: %s",
                _compact_error_message(error),
            )
            return
        logger.exception("Batched message write flush failed because PostgreSQL returned an error.")

    @staticmethod
    def _build_fallback_message_id(event: TwitchChatMessageEvent) -> str:
        raise ValueError("Twitch IRC message is missing message_id.")

    @classmethod
    def _resolve_message_id(cls, event: TwitchChatMessageEvent) -> str:
        return event.message_id or cls._build_fallback_message_id(event)


def _is_transient_postgres_disconnect(error: psycopg.Error) -> bool:
    message = str(error).lower()
    transient_fragments = (
        "server closed the connection unexpectedly",
        "database system is shutting down",
        "connection is lost",
        "connection failed",
        "terminating connection due to administrator command",
        "consuming input failed",
    )
    return isinstance(error, psycopg.OperationalError) and any(fragment in message for fragment in transient_fragments)


def _compact_error_message(error: BaseException) -> str:
    return " ".join(str(error).split())
