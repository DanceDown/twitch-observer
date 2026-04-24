from __future__ import annotations

"""Startup synchronization for persisted Twitch IRC channel subscriptions."""

import asyncio
import logging
from dataclasses import dataclass

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError
from src.database.connection import ChannelRepository

logger = logging.getLogger(__name__)


class IRCBootstrapManager:
    """Minimal IRC adapter surface needed during startup sync."""

    async def wait_until_connected(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def join_channel(self, channel_login: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(slots=True)
class IRCBootstrapService:
    """Re-join persisted Twitch channels when the app starts."""

    channel_repository: ChannelRepository
    twitch_api: TwitchAPIClient
    irc_manager: IRCBootstrapManager
    connect_timeout_seconds: float

    async def sync_persisted_channels(self) -> None:
        """Load all stored channels from the DB and join them on IRC."""
        channel_ids = self.channel_repository.list_all_twitch_channel_ids()
        if not channel_ids:
            logger.debug("No persisted Twitch channels found for IRC startup sync.")
            return

        try:
            await asyncio.wait_for(self.irc_manager.wait_until_connected(), timeout=self.connect_timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out waiting for Twitch IRC to become ready; persisted channels were not re-joined yet."
            )
            return

        logger.debug("Rehydrating %s persisted Twitch IRC channel subscriptions from the database.", len(channel_ids))
        for twitch_channel_id in channel_ids:
            try:
                user = await self.twitch_api.get_user_by_id(twitch_channel_id)
            except TwitchAPIError as error:
                logger.warning(
                    "Could not resolve stored Twitch channel id=%s during IRC startup sync: %s",
                    twitch_channel_id,
                    error,
                )
                continue
            await self.irc_manager.join_channel(user.login)
