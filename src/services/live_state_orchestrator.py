"""Direct orchestrator for tracked-channel live state transitions."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.events.event_types import TwitchChannelLiveStateChangedEvent
from src.services.channel_event_notification_service import (
    ChannelEventNotificationService,
    ChannelLiveStatePersistenceService,
)
from src.services.replies.channel_event_auto_reply_service import ChannelEventAutoReplyService
from src.utils.async_utils import resolve_awaitable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LiveStateChangeOrchestrator:
    """Execute live-state side effects in explicit order."""

    persistence: ChannelLiveStatePersistenceService
    notifications: ChannelEventNotificationService
    auto_replies: ChannelEventAutoReplyService

    async def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None:
        await resolve_awaitable(self.persistence.handle_change(event))
        try:
            suppressed_events = await self.auto_replies.handle_channel_live_state_changed(event)
        except Exception:
            logger.exception(
                "Channel-event auto-reply handling failed twitch_channel_id=%s is_live=%s",
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
