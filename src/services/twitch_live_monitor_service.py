"""Periodic app-token-based Twitch live-state monitor for tracked channels."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import psycopg

from src.gateways.twitch_api import TwitchAPIError
from src.database.connection import ChannelRepository
from src.errors import DatabasePoolExhaustedError
from src.events.twitch_events import TwitchChannelLiveStateChangedEvent
from src.services.twitch_gateways import TwitchLiveMonitorGateway
from src.services.twitch_runtime import safe_get_twitch_user_by_id

logger = logging.getLogger(__name__)


class LiveStateChangeHandler(Protocol):
    """Async handler for live/offline transition events."""

    async def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None: ...


def _batched(values: list[str], batch_size: int) -> list[list[str]]:
    effective_batch_size = max(1, batch_size)
    return [values[index : index + effective_batch_size] for index in range(0, len(values), effective_batch_size)]


@dataclass(slots=True)
class TwitchLiveMonitorService:
    """Poll Twitch Helix for tracked channel live state without needing a linked user account."""

    channel_repository: ChannelRepository
    twitch_api: TwitchLiveMonitorGateway
    poll_interval_seconds: float
    batch_size: int
    refresh_on_startup: bool
    on_change: LiveStateChangeHandler
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _wake_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        """Start the live monitor loop once."""
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop(), name="twitch-live-monitor")

    async def stop(self) -> None:
        """Stop the live monitor loop and wait for the task to finish."""
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def notify_tracked_channels_changed(self) -> None:
        """Wake the monitor early when tracked channels change."""
        logger.debug("Received tracked-channel change signal for live monitor sync.")
        self._wake_event.set()

    async def _run_loop(self) -> None:
        if self.refresh_on_startup:
            try:
                await self.sync_once(notify_transitions=False)
            except DatabasePoolExhaustedError:
                logger.error("Live monitor startup sync skipped because the database pool is exhausted.")
            except psycopg.Error:
                logger.exception("Live monitor startup sync failed because PostgreSQL returned an error.")
            except TwitchAPIError as error:
                logger.warning("Live monitor startup sync skipped because Twitch is unavailable: %s", error)
            except Exception:
                logger.exception("Live monitor startup sync failed unexpectedly; periodic sync will continue.")

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=self.poll_interval_seconds)
                self._wake_event.clear()
            except TimeoutError:
                pass

            if self._stop_event.is_set():
                break

            try:
                await self.sync_once(notify_transitions=True)
            except DatabasePoolExhaustedError:
                logger.error("Live monitor periodic sync skipped because the database pool is exhausted.")
            except psycopg.Error:
                logger.exception("Live monitor periodic sync failed because PostgreSQL returned an error.")
            except TwitchAPIError as error:
                logger.warning("Live monitor periodic sync skipped because Twitch is unavailable: %s", error)
            except Exception:
                logger.exception("Live monitor periodic sync failed unexpectedly; the monitor will continue.")

    async def sync_once(self, *, notify_transitions: bool) -> None:
        """Refresh the live state for all tracked channels."""
        tracked_channels = await self.channel_repository.list_distinct_channel_states()
        if not tracked_channels:
            logger.debug("Skipping live monitor sync because no Twitch channels are tracked.")
            return

        channel_ids = [channel.twitch_channel_id for channel in tracked_channels]
        live_ids: set[str] = set()
        try:
            for batch in _batched(channel_ids, self.batch_size):
                live_ids.update(await self.twitch_api.get_live_user_ids(batch))
        except TwitchAPIError as error:
            logger.warning("Failed to refresh Twitch live states for batch polling: %s", error)
            return

        changed_at = datetime.now(UTC)
        tracked_channels_by_id = {channel.twitch_channel_id: channel for channel in tracked_channels}
        for twitch_channel_id in channel_ids:
            previous = tracked_channels_by_id[twitch_channel_id]
            current_is_live = twitch_channel_id in live_ids
            if previous.is_live is current_is_live:
                continue

            if not notify_transitions or previous.is_live is None:
                await self.channel_repository.set_live_state_for_twitch_channel(
                    twitch_channel_id=twitch_channel_id,
                    is_live=current_is_live,
                    changed_at=changed_at.isoformat(),
                )

                continue

            twitch_user = await safe_get_twitch_user_by_id(self.twitch_api, twitch_channel_id)
            event = TwitchChannelLiveStateChangedEvent(
                twitch_channel_id=twitch_channel_id,
                twitch_channel_login=None if twitch_user is None else twitch_user.login,
                is_live=current_is_live,
                changed_at=changed_at,
            )
            try:
                await self.on_change.handle_change(event)
            except asyncio.CancelledError:
                raise
            except DatabasePoolExhaustedError:
                logger.error(
                    "Live-state transition skipped because the database pool is exhausted twitch_channel_id=%s is_live=%s",
                    twitch_channel_id,
                    current_is_live,
                )
            except psycopg.Error:
                logger.exception(
                    "Live-state transition failed because PostgreSQL returned an error twitch_channel_id=%s is_live=%s",
                    twitch_channel_id,
                    current_is_live,
                )
            except TwitchAPIError as error:
                logger.warning(
                    "Live-state transition failed because Twitch is unavailable twitch_channel_id=%s is_live=%s: %s",
                    twitch_channel_id,
                    current_is_live,
                    error,
                )
            except Exception:
                logger.exception(
                    "Live-state transition failed unexpectedly twitch_channel_id=%s is_live=%s",
                    twitch_channel_id,
                    current_is_live,
                )
