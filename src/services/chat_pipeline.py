"""Direct chat-message processing pipeline for Twitch IRC intake."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from src.events.twitch_events import TwitchChatMessageEvent
from src.services.chat import ChatMessageReactionService
from src.services.chat_delivery_context import (
    ChatMessageCompletionNotifier,
    bind_chat_message_sequence,
    reset_chat_message_sequence,
)
from src.services.message_ingest_service import MessageIngestService
from src.services.twitch_user_directory_service import TwitchUserDirectoryIngestService

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _QueuedChatMessage:
    sequence: int
    event: TwitchChatMessageEvent


@dataclass(slots=True)
class ChatMessageProcessingService:
    """Process one inbound Twitch chat message in explicit pipeline order."""

    message_ingest: MessageIngestService
    user_observer: TwitchUserDirectoryIngestService
    reactions: ChatMessageReactionService
    queue_size: int = 10000
    worker_count: int = 4
    stop_timeout_seconds: float = 30
    completion_notifier: ChatMessageCompletionNotifier | None = None
    _queue: asyncio.Queue[_QueuedChatMessage | None] | None = field(default=None, init=False)
    _workers: list[asyncio.Task[None]] | None = field(default=None, init=False)
    _next_sequence: int = field(default=1, init=False)
    _message_sequences: dict[str, int] = field(default_factory=dict, init=False)
    _completion_events: dict[int, asyncio.Event] = field(default_factory=dict, init=False)

    async def process(self, message: TwitchChatMessageEvent) -> None:
        await self.message_ingest.handle_chat_message(message)
        await self.user_observer.handle_chat_message(message)
        await self.reactions.handle_chat_message(message)
        logger.debug(
            "Completed chat pipeline for channel=%s author=%s message_id=%s",
            message.channel_login,
            message.author_login,
            message.message_id,
        )

    async def start(self) -> None:
        """Start bounded background workers for IRC intake."""
        if self._workers is not None:
            return
        self._queue = asyncio.Queue(maxsize=max(1, self.queue_size))
        self._message_sequences.clear()
        self._completion_events.clear()
        self._workers = [
            asyncio.create_task(self._run_worker(index), name=f"chat-message-worker-{index}") for index in range(max(1, self.worker_count))
        ]

    async def stop(self) -> None:
        """Drain queued chat messages and stop workers."""
        queue = self._queue
        workers = self._workers
        if queue is None or workers is None:
            return
        stop_timeout_seconds = max(0.1, self.stop_timeout_seconds)
        try:
            await asyncio.wait_for(queue.join(), timeout=stop_timeout_seconds)
            for _ in workers:
                await queue.put(None)
            await asyncio.wait_for(asyncio.gather(*workers, return_exceptions=True), timeout=stop_timeout_seconds)
        except TimeoutError:
            logger.warning("Chat message processing did not drain in time; cancelling workers.")
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            self._queue = None
            self._workers = None
            self._message_sequences.clear()
            self._completion_events.clear()

    async def enqueue(self, message: TwitchChatMessageEvent) -> None:
        """Queue an inbound message, or process directly when workers are not running."""
        queue = self._queue
        if queue is None:
            await self.process(message)
            return
        queued_message = self._build_queued_message(message)
        await self._reserve_queued_message(queued_message)
        try:
            await queue.put(queued_message)
        except Exception:
            await self._complete_queued_message(queued_message)
            raise

    async def _run_worker(self, index: int) -> None:
        queue = self._queue
        if queue is None:
            return
        while True:
            queued_message = await queue.get()
            try:
                if queued_message is None:
                    return
                await self._wait_for_reply_parent(queued_message)
                token = bind_chat_message_sequence(queued_message.sequence)
                try:
                    await self.process(queued_message.event)
                finally:
                    reset_chat_message_sequence(token)
                    await self._complete_queued_message(queued_message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Chat message worker %s failed while processing message_id=%s channel=%s author=%s.",
                    index,
                    None if queued_message is None else queued_message.event.message_id,
                    None if queued_message is None else queued_message.event.channel_login,
                    None if queued_message is None else queued_message.event.author_login,
                )
            finally:
                queue.task_done()

    def _build_queued_message(self, event: TwitchChatMessageEvent) -> _QueuedChatMessage:
        sequence = self._next_sequence
        self._next_sequence += 1
        return _QueuedChatMessage(sequence=sequence, event=event)

    async def _reserve_queued_message(self, queued_message: _QueuedChatMessage) -> None:
        if queued_message.event.message_id:
            self._message_sequences[queued_message.event.message_id] = queued_message.sequence
        self._completion_events[queued_message.sequence] = asyncio.Event()
        if self.completion_notifier is None:
            return
        try:
            await self.completion_notifier.reserve_message(queued_message.sequence)
        except Exception:
            logger.exception("Failed to reserve ordered delivery slot for chat sequence=%s.", queued_message.sequence)

    async def _complete_queued_message(self, queued_message: _QueuedChatMessage) -> None:
        if queued_message.event.message_id:
            self._message_sequences.pop(queued_message.event.message_id, None)
        event = self._completion_events.pop(queued_message.sequence, None)
        if event is not None:
            event.set()
        if self.completion_notifier is None:
            return
        try:
            await self.completion_notifier.complete_message(queued_message.sequence)
        except Exception:
            logger.exception("Failed to complete ordered delivery slot for chat sequence=%s.", queued_message.sequence)

    async def _wait_for_reply_parent(self, queued_message: _QueuedChatMessage) -> None:
        parent_message_id = queued_message.event.reply_parent_message_id
        if not parent_message_id:
            return
        parent_sequence = self._message_sequences.get(parent_message_id)
        if parent_sequence is None or parent_sequence >= queued_message.sequence:
            return
        parent_completion = self._completion_events.get(parent_sequence)
        if parent_completion is None:
            return
        await parent_completion.wait()
