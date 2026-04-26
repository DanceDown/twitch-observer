from __future__ import annotations

"""Background service updating the bot's Discord custom status from recent Twitch messages."""

import asyncio
import random
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.database.connection import MessageRepository


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
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    async def start(self) -> None:
        """Start the periodic status-update loop once."""
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="discord-presence-service")

    async def stop(self) -> None:
        """Stop the periodic status-update loop."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def poll_once(self) -> None:
        """Choose one recent message and publish it as Discord custom status."""
        since = datetime.now(UTC) - timedelta(minutes=self.lookback_minutes)
        messages = self.message_repository.list_recent_messages(since=since, limit=self.message_limit)
        if not messages:
            return
        selected = random.choice(messages)
        text = self._format_status(selected.content, selected.username)
        if text:
            await self.notifier.set_status_text(text)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            await self.poll_once()
            await asyncio.sleep(self.poll_interval_seconds)

    def _format_status(self, content: str, username: str) -> str:
        cleaned = " ".join(content.split())
        suffix = f" ~{username}"
        if not cleaned:
            return ""
        max_content_length = max(1, self.max_status_length - len(suffix))
        if len(cleaned) > max_content_length:
            cleaned = cleaned[: max_content_length - 1].rstrip() + "…"
        return f"\"{cleaned}\"{suffix}"
