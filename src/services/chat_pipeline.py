"""Direct chat-message processing pipeline for Twitch IRC intake."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.events.event_types import TwitchChatMessageEvent
from src.services.message_ingest_service import MessageIngestService
from src.services.patterns.tracking_service import PatternTrackingService
from src.services.replies.pattern_auto_reply_service import AutoReplyService
from src.services.twitch_user_directory_service import TwitchUserDirectoryIngestService
from src.utils.async_utils import resolve_awaitable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChatMessageProcessingService:
    """Process one inbound Twitch chat message in explicit pipeline order."""

    message_ingest: MessageIngestService
    user_observer: TwitchUserDirectoryIngestService
    pattern_tracking: PatternTrackingService
    auto_reply: AutoReplyService

    async def process(self, message: TwitchChatMessageEvent) -> None:
        await resolve_awaitable(self.message_ingest.handle_chat_message(message))
        await resolve_awaitable(self.user_observer.handle_chat_message(message))
        await resolve_awaitable(self.pattern_tracking.handle_chat_message(message))
        await resolve_awaitable(self.auto_reply.handle_chat_message(message))
        logger.debug(
            "Completed chat pipeline for channel=%s author=%s message_id=%s",
            message.channel_login,
            message.author_login,
            message.message_id,
        )
