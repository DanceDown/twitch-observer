"""Batched write wrapper for hot-path Twitch chat message persistence."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

import psycopg

from src.database.connection import MessageRepository, RecentMessageRecord
from src.errors import DatabasePoolExhaustedError, MissingTwitchMessageIdError
from src.events.twitch_events import TwitchChatMessageEvent

logger = logging.getLogger(__name__)
_SPOOL_VERSION = 1


class BatchedMessageSpoolError(ValueError):
    """Raised when a persisted write-spool file has an invalid shape."""

    @classmethod
    def payload_not_object(cls) -> BatchedMessageSpoolError:
        """Build an error for spool files whose root value is not an object."""
        return cls("Batched message write spool payload must be an object.")

    @classmethod
    def unsupported_version(cls, version: object) -> BatchedMessageSpoolError:
        """Build an error for spool files from unsupported future/old formats."""
        return cls(f"Unsupported batched message write spool version: {version!r}.")

    @classmethod
    def malformed_lists(cls) -> BatchedMessageSpoolError:
        """Build an error for spool files with malformed message lists."""
        return cls("Batched message write spool lists are malformed.")

    @classmethod
    def thread_match_not_object(cls) -> BatchedMessageSpoolError:
        """Build an error for malformed thread-match entries."""
        return cls("Batched message write spool thread match must be an object.")

    @classmethod
    def event_not_object(cls) -> BatchedMessageSpoolError:
        """Build an error for malformed message event entries."""
        return cls("Batched message write spool event must be an object.")

    @classmethod
    def missing_field(cls, key: str) -> BatchedMessageSpoolError:
        """Build an error for required spool event fields missing from the payload."""
        return cls(f"Batched message write spool field {key!r} is missing.")


@runtime_checkable
class _BatchMessageWriteRepository(Protocol):
    async def flush_write_batch(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None:
        """Persist a prepared batch of raw messages and thread matches."""
        ...


@dataclass(slots=True)
class BatchedMessageRepository(MessageRepository):
    """Batch hot-path message writes while keeping reads consistent."""

    repository: MessageRepository
    batch_size: int = 50
    flush_interval_seconds: float = 0.25
    spool_path: str | None = None
    _pending_messages: dict[str, TwitchChatMessageEvent] = field(default_factory=dict, init=False)
    _pending_matches: dict[tuple[int, str], tuple[int, TwitchChatMessageEvent]] = field(default_factory=dict, init=False)
    _queue_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _wake_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _spool_restore_pending: bool = field(default=False, init=False)

    async def start(self) -> None:
        """Restore spooled writes and start the background flush loop."""
        await self._restore_spooled_writes()
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop(), name="message-write-batcher")

    async def stop(self) -> None:
        """Stop the background loop and flush remaining writes for shutdown."""
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
        """Queue one incoming Twitch message for batched persistence."""
        should_flush_now = await self._enqueue_message(event)
        if should_flush_now and self._task is None:
            await self.flush()

    async def save_bot_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        """Flush pending inbound messages before storing a bot-sent message."""
        await self.flush()
        await self.repository.save_bot_twitch_message(event)

    async def mark_message_matched_in_thread(
        self,
        *,
        thread_id: int,
        event: TwitchChatMessageEvent,
    ) -> None:
        """Queue that one Twitch message matched inside one thread."""
        should_flush_now = await self._enqueue_match(thread_id=thread_id, event=event)
        if should_flush_now and self._task is None:
            await self.flush()

    async def list_recent_messages(
        self,
        *,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        """Flush pending writes before returning recent cross-channel messages."""
        await self.flush()
        return await self.repository.list_recent_messages(since=since, limit=limit)

    async def list_recent_messages_for_channel(
        self,
        *,
        twitch_channel_id: str,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        """Flush pending writes before returning recent messages for one channel."""
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
        """Flush pending writes before returning recent messages for one thread."""
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
        """Flush pending writes before reading one thread-linked message."""
        await self.flush()
        return await self.repository.get_thread_message(
            thread_id=thread_id,
            message_id=message_id,
        )

    async def flush(self) -> None:
        """Persist all queued message writes, requeuing snapshots on DB failure."""
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
                await self._clear_restored_spool_after_success()

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

    async def _snapshot_pending(
        self,
    ) -> tuple[tuple[TwitchChatMessageEvent, ...], tuple[tuple[int, TwitchChatMessageEvent], ...]]:
        async with self._queue_lock:
            return tuple(self._pending_messages.values()), tuple(self._pending_matches.values())

    async def _flush_snapshot(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None:
        if isinstance(self.repository, _BatchMessageWriteRepository):
            await self.repository.flush_write_batch(
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
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.flush_interval_seconds)
            if self._stop_event.is_set():
                break
            try:
                await self.flush()
            except DatabasePoolExhaustedError:
                logger.exception("Batched message write flush failed because the database pool is exhausted.")
            except psycopg.Error as error:
                self._log_postgres_flush_error(error)
        await self._flush_for_shutdown()

    async def _flush_for_shutdown(self) -> None:
        try:
            await self.flush()
        except DatabasePoolExhaustedError:
            spooled_path = await self._spool_pending_writes()
            logger.warning(
                "Final batched message write flush skipped during shutdown because the database pool is exhausted%s.",
                _spooled_hint(spooled_path),
            )
        except psycopg.Error as error:
            spooled_path = await self._spool_pending_writes()
            if _is_transient_postgres_disconnect(error):
                logger.warning(
                    "Final batched message write flush skipped during shutdown because PostgreSQL is unavailable%s: %s",
                    _spooled_hint(spooled_path),
                    _compact_error_message(error),
                )
                return
            logger.exception("Final batched message write flush failed during shutdown%s.", _spooled_hint(spooled_path))

    async def _restore_spooled_writes(self) -> None:
        path = self._spool_file_path()
        if path is None or not path.exists():
            return
        try:
            message_events, thread_matches = _read_spool_file(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.exception("Could not read batched message write spool %s; leaving it in place.", path)
            return
        if not message_events and not thread_matches:
            _remove_spool_file(path)
            return
        await self._requeue_snapshot(message_events=message_events, thread_matches=thread_matches)
        self._spool_restore_pending = True
        try:
            await self.flush()
        except DatabasePoolExhaustedError:
            logger.warning("Could not replay batched message write spool because the database pool is exhausted; retrying in background.")
        except psycopg.Error as error:
            if _is_transient_postgres_disconnect(error):
                logger.warning(
                    "Could not replay batched message write spool because PostgreSQL is unavailable; retrying in background: %s",
                    _compact_error_message(error),
                )
                return
            logger.exception("Could not replay batched message write spool because PostgreSQL returned an error; retrying in background.")

    async def _spool_pending_writes(self) -> Path | None:
        path = self._spool_file_path()
        if path is None:
            return None
        message_events, thread_matches = await self._snapshot_pending()
        if not message_events and not thread_matches:
            return None
        try:
            _write_spool_file(path, message_events=message_events, thread_matches=thread_matches)
        except OSError:
            logger.exception("Could not spool pending batched message writes to %s.", path)
            return None
        return path

    async def _clear_restored_spool_after_success(self) -> None:
        if not self._spool_restore_pending:
            return
        path = self._spool_file_path()
        if path is not None:
            _remove_spool_file(path)
        self._spool_restore_pending = False
        logger.info("Replayed spooled batched message writes into PostgreSQL.")

    def _spool_file_path(self) -> Path | None:
        if self.spool_path is None:
            return None
        normalized_path = self.spool_path.strip()
        return Path(normalized_path) if normalized_path else None

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
    def _build_fallback_message_id() -> str:
        raise MissingTwitchMessageIdError

    @classmethod
    def _resolve_message_id(cls, event: TwitchChatMessageEvent) -> str:
        return event.message_id or cls._build_fallback_message_id()


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


def _spooled_hint(spooled_path: Path | None) -> str:
    return f"; pending writes were spooled to {spooled_path}" if spooled_path is not None else ""


def _write_spool_file(
    path: Path,
    *,
    message_events: tuple[TwitchChatMessageEvent, ...],
    thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
) -> None:
    payload = {
        "version": _SPOOL_VERSION,
        "messages": [_event_to_payload(event) for event in message_events],
        "thread_matches": [
            {
                "thread_id": thread_id,
                "event": _event_to_payload(event),
            }
            for thread_id, event in thread_matches
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary_path.replace(path)


def _read_spool_file(path: Path) -> tuple[tuple[TwitchChatMessageEvent, ...], tuple[tuple[int, TwitchChatMessageEvent], ...]]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BatchedMessageSpoolError.payload_not_object()
    if payload.get("version") != _SPOOL_VERSION:
        raise BatchedMessageSpoolError.unsupported_version(payload.get("version"))
    messages = payload.get("messages", [])
    thread_matches = payload.get("thread_matches", [])
    if not isinstance(messages, list) or not isinstance(thread_matches, list):
        raise BatchedMessageSpoolError.malformed_lists()
    return (
        tuple(_event_from_payload(message) for message in messages),
        tuple(_thread_match_from_payload(match) for match in thread_matches),
    )


def _remove_spool_file(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        logger.exception("Could not remove batched message write spool %s.", path)
        return False
    return True


def _thread_match_from_payload(payload: object) -> tuple[int, TwitchChatMessageEvent]:
    if not isinstance(payload, dict):
        raise BatchedMessageSpoolError.thread_match_not_object()
    return int(_required_value(payload, "thread_id")), _event_from_payload(_required_value(payload, "event"))


def _event_to_payload(event: TwitchChatMessageEvent) -> dict[str, object]:
    return {
        "channel_login": event.channel_login,
        "author_login": event.author_login,
        "content": event.content,
        "author_display_name": event.author_display_name,
        "message_id": event.message_id,
        "broadcaster_id": event.broadcaster_id,
        "author_id": event.author_id,
        "color": event.color,
        "reply_parent_message_id": event.reply_parent_message_id,
        "message_kind": event.message_kind,
        "notice_type": event.notice_type,
        "system_message": event.system_message,
        "sent_at": event.sent_at.isoformat(),
        "raw_line": event.raw_line,
        "raw_tags": dict(event.raw_tags),
    }


def _event_from_payload(payload: object) -> TwitchChatMessageEvent:
    if not isinstance(payload, dict):
        raise BatchedMessageSpoolError.event_not_object()
    return TwitchChatMessageEvent(
        channel_login=_required_str(payload, "channel_login"),
        author_login=_required_str(payload, "author_login"),
        content=_required_str(payload, "content"),
        author_display_name=_optional_str(payload, "author_display_name"),
        message_id=_optional_str(payload, "message_id"),
        broadcaster_id=_optional_str(payload, "broadcaster_id"),
        author_id=_optional_str(payload, "author_id"),
        color=_optional_str(payload, "color"),
        reply_parent_message_id=_optional_str(payload, "reply_parent_message_id"),
        message_kind=_required_str(payload, "message_kind"),
        notice_type=_optional_str(payload, "notice_type"),
        system_message=_optional_str(payload, "system_message"),
        sent_at=_datetime_from_payload(_required_value(payload, "sent_at")),
        raw_line=_optional_str(payload, "raw_line"),
        raw_tags=_raw_tags_from_payload(payload.get("raw_tags", {})),
    )


def _required_value(payload: dict[str, object], key: str) -> object:
    if key not in payload or payload[key] is None:
        raise BatchedMessageSpoolError.missing_field(key)
    return payload[key]


def _required_str(payload: dict[str, object], key: str) -> str:
    return str(_required_value(payload, key))


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return None if value is None else str(value)


def _datetime_from_payload(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _raw_tags_from_payload(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}
