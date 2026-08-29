"""Background service updating the bot's Discord custom status from recent Twitch messages."""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.database.connection import MessageRepository

logger = logging.getLogger(__name__)


class DiscordPresenceStatusSender:
    """Interface for pushing one custom status text to the Discord client."""

    async def set_status_text(self, text: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(slots=True)
class DiscordPresenceService:
    """Periodically publish a random recent Twitch message as the bot's custom status."""

    message_repository: MessageRepository
    notifier: DiscordPresenceStatusSender
    poll_interval_seconds: float
    lookback_minutes: int
    message_limit: int
    max_status_length: int
    status_update_timeout_seconds: float = 15.0
    watchdog_interval_seconds: float = 60.0
    stale_after_seconds: float = 180.0
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _watchdog_task: asyncio.Task[None] | None = field(default=None, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _last_status_text: str | None = field(default=None, init=False)
    _last_poll_started_at: datetime | None = field(default=None, init=False)
    _last_poll_finished_at: datetime | None = field(default=None, init=False)

    async def start(self) -> None:
        """Start the periodic status-update loop once."""
        self._stop_event.clear()
        self.status_update_timeout_seconds = max(0.001, self.status_update_timeout_seconds)
        self.watchdog_interval_seconds = max(1.0, self.watchdog_interval_seconds)
        self.stale_after_seconds = max(self.stale_after_seconds, self.poll_interval_seconds * 2)
        if self._last_poll_finished_at is None:
            self._last_poll_finished_at = datetime.now(UTC)
        self._start_worker_task()
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._run_watchdog(), name="discord-presence-watchdog")

    async def stop(self) -> None:
        """Stop the periodic status-update loop."""
        self._stop_event.set()
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def poll_once(self) -> None:
        """Choose one recent message and publish it as Discord custom status."""
        self._last_poll_started_at = datetime.now(UTC)
        try:
            since = datetime.now(UTC) - timedelta(minutes=self.lookback_minutes)
            messages = await self.message_repository.list_recent_messages(since=since, limit=self.message_limit)
            if not messages:
                return
            candidate_texts = [self._format_status(message.content, message.username) for message in messages]
            available_texts = tuple(dict.fromkeys(text for text in candidate_texts if text))
            if not available_texts:
                return
            if len(available_texts) == 1:
                text = available_texts[0]
            else:
                options = tuple(text for text in available_texts if text != self._last_status_text)
                text = random.choice(options or available_texts)
            if text:
                if await self._publish_status_text(text):
                    self._last_status_text = text
        finally:
            self._last_poll_finished_at = datetime.now(UTC)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Discord presence poll failed; keeping worker alive.")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _run_watchdog(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(self.watchdog_interval_seconds)
            if self._stop_event.is_set():
                break
            try:
                await self._watchdog_once()
            except Exception:
                logger.exception("Discord presence watchdog failed; keeping watchdog alive.")

    async def _watchdog_once(self) -> None:
        if self._task is None:
            logger.warning("Discord presence worker is missing; starting it again.")
            self._start_worker_task()
            return
        if self._task.done():
            logger.warning("Discord presence worker stopped unexpectedly; restarting it.")
            self._task = None
            self._start_worker_task()
            return
        last_progress_at = self._last_poll_finished_at or self._last_poll_started_at
        if last_progress_at is None:
            return
        age_seconds = (datetime.now(UTC) - last_progress_at).total_seconds()
        if age_seconds > self.stale_after_seconds:
            logger.warning(
                "Discord presence worker appears stale; no completed poll for %.1f seconds (threshold %.1f); restarting it.",
                age_seconds,
                self.stale_after_seconds,
            )
            self._restart_worker_task()

    async def _publish_status_text(self, text: str) -> bool:
        timeout_seconds = max(0.001, self.status_update_timeout_seconds)
        try:
            await asyncio.wait_for(self.notifier.set_status_text(text), timeout=timeout_seconds)
        except TimeoutError:
            logger.warning(
                "Discord presence update timed out after %.1f seconds; will retry on the next poll.",
                timeout_seconds,
            )
            return False
        return True

    def _format_status(self, content: str, username: str) -> str:
        cleaned = " ".join(content.split())
        suffix = f" ~{username}"
        if not cleaned:
            return ""
        max_content_length = max(1, self.max_status_length - len(suffix))
        if len(cleaned) > max_content_length:
            cleaned = cleaned[: max_content_length - 1].rstrip() + "..."
        return f'"{cleaned}"{suffix}'

    def _start_worker_task(self) -> None:
        if self._stop_event.is_set():
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="discord-presence-service")

    def _restart_worker_task(self) -> None:
        if self._stop_event.is_set():
            return
        old_task = self._task
        if old_task is not None and not old_task.done():
            old_task.cancel()
        self._task = None
        self._start_worker_task()
