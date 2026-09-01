"""Direct orchestrator for tracked-channel live state transitions."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.errors import DatabasePoolExhaustedError
from src.events.twitch_events import TwitchChannelLiveStateChangedEvent
from src.gateways.twitch_api import TwitchAPIError
from src.services.channel_event_notification_service import (
    ChannelEventNotificationService,
    ChannelLiveStatePersistenceService,
)
from src.services.replies.channel_event_auto_reply_service import ChannelEventAutoReplyService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LiveStateChangeOrchestrator:
    """Execute live-state side effects in explicit order."""

    persistence: ChannelLiveStatePersistenceService
    notifications: ChannelEventNotificationService
    auto_replies: ChannelEventAutoReplyService

    async def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None:
        """Persist one transition, send auto-replies, then notify Discord."""
        await self.persistence.handle_change(event)
        try:
            suppressed_events = await self.auto_replies.handle_channel_live_state_changed(event)
        except DatabasePoolExhaustedError:
            logger.exception(
                "Channel-event auto-reply handling skipped because the database pool is exhausted twitch_channel_id=%s is_live=%s",
                event.twitch_channel_id,
                event.is_live,
            )
            suppressed_events = set()
        except TwitchAPIError:
            logger.exception(
                "Channel-event auto-reply handling failed because Twitch rejected the request twitch_channel_id=%s is_live=%s",
                event.twitch_channel_id,
                event.is_live,
            )
            suppressed_events = set()
        await self.notifications.handle_change(event, suppressed_events=suppressed_events)
        logger.debug(
            "Completed live-state orchestration twitch_channel_id=%s is_live=%s",
            event.twitch_channel_id,
            event.is_live,
        )
