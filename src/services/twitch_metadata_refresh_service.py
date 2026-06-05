"""Background refresh worker for the persistent Twitch user metadata cache."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field

from src.gateways.twitch_api import TwitchAPIError
from src.services.twitch_user_directory_service import TwitchUserDirectoryService

logger = logging.getLogger(__name__)


def _batched(values: tuple[str, ...], batch_size: int) -> tuple[tuple[str, ...], ...]:
    effective_batch_size = max(1, batch_size)
    return tuple(values[index : index + effective_batch_size] for index in range(0, len(values), effective_batch_size))


@dataclass(slots=True)
class TwitchMetadataRefreshService:
    """Refresh the full persisted Twitch metadata cache in evenly spaced batches."""

    directory: TwitchUserDirectoryService
    refresh_interval_seconds: float
    request_spacing_seconds: float
    batch_size: int = 100
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="twitch-metadata-refresh")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run_once(self) -> None:
        cached_records = await self.directory.list_cached_users()
        cached_user_ids = tuple(dict.fromkeys(record.twitch_user_id for record in cached_records if record.twitch_user_id))
        if not cached_user_ids:
            logger.debug("Skipping Twitch metadata refresh because the persistent cache is empty.")
            return

        batches = _batched(cached_user_ids, max(1, self.batch_size))
        spacing_seconds = self._spacing_seconds_for_batch_count(len(batches))
        for index, batch in enumerate(batches):
            try:
                users = await self.directory.get_users_by_ids(batch)
            except TwitchAPIError as error:
                logger.warning("Failed to refresh Twitch metadata batch (%s ids): %s", len(batch), error)
                continue
            await self.directory.upsert_users_from_api(users)
            if index < len(batches) - 1:
                await self._wait_or_stop(spacing_seconds)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            started_at = asyncio.get_running_loop().time()
            try:
                await self.run_once()
            except Exception:
                logger.exception("Twitch metadata refresh pass failed.")
            elapsed = asyncio.get_running_loop().time() - started_at
            remaining = max(0.0, self.refresh_interval_seconds - elapsed)
            if remaining <= 0:
                continue
            await self._wait_or_stop(remaining)

    async def _wait_or_stop(self, seconds: float) -> None:
        if seconds <= 0:
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            return

    def _spacing_seconds_for_batch_count(self, batch_count: int) -> float:
        if batch_count <= 1:
            return 0.0
        if self.request_spacing_seconds > 0:
            return self.request_spacing_seconds
        if self.refresh_interval_seconds <= 0:
            return 0.0
        return self.refresh_interval_seconds / batch_count
