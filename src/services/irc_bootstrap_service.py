"""Startup synchronization for persisted Twitch IRC channel subscriptions."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field

from src.gateways.twitch_api import TwitchAPIError
from src.database.connection import ChannelRepository
from src.services.twitch_gateways import TwitchChannelLookup, TwitchIRCConnectionGateway
from src.utils.async_utils import resolve_awaitable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IRCBootstrapService:
    """Re-join persisted Twitch channels when the app starts."""

    channel_repository: ChannelRepository
    twitch_api: TwitchChannelLookup
    irc_gateway: TwitchIRCConnectionGateway
    connect_timeout_seconds: float
    resync_interval_seconds: float | None = None
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    async def start_periodic_sync(self) -> None:
        """Start periodic idempotent IRC re-joins for persisted channels."""
        if self.resync_interval_seconds is None or self.resync_interval_seconds <= 0:
            return
        if self._task is None:
            self._task = asyncio.create_task(self._run_periodic_sync(), name="twitch-irc-channel-resync")

    async def stop_periodic_sync(self) -> None:
        """Stop the periodic IRC re-join loop."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def sync_persisted_channels(self) -> None:
        """Load all stored channels from the DB and join them on IRC."""
        channel_ids = await resolve_awaitable(self.channel_repository.list_all_twitch_channel_ids())
        if not channel_ids:
            logger.debug("No persisted Twitch channels found for IRC startup sync.")
            return

        try:
            await asyncio.wait_for(self.irc_gateway.wait_until_connected(), timeout=self.connect_timeout_seconds)
        except TimeoutError:
            logger.warning("Timed out waiting for Twitch IRC to become ready; persisted channels were not re-joined yet.")
            return

        logger.debug("Rehydrating %s persisted Twitch IRC channel subscriptions from the database.", len(channel_ids))
        for twitch_channel_id in channel_ids:
            try:
                user = await self.twitch_api.get_channel_by_id(twitch_channel_id)
            except TwitchAPIError as error:
                logger.warning(
                    "Could not resolve stored Twitch channel id=%s during IRC startup sync: %s",
                    twitch_channel_id,
                    error,
                )
                continue
            await self.irc_gateway.join_channel(user.login)

    async def _run_periodic_sync(self) -> None:
        if self.resync_interval_seconds is None:
            return
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.resync_interval_seconds)
            except TimeoutError:
                await self.sync_persisted_channels()
