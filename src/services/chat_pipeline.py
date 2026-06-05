"""Direct chat-message processing pipeline for Twitch IRC intake."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.events.event_types import TwitchChatMessageEvent
from src.services.chat import ChatMessageReactionService
from src.services.message_ingest_service import MessageIngestService
from src.services.twitch_user_directory_service import TwitchUserDirectoryIngestService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChatMessageProcessingService:
    """Process one inbound Twitch chat message in explicit pipeline order."""

    message_ingest: MessageIngestService
    user_observer: TwitchUserDirectoryIngestService
    reactions: ChatMessageReactionService

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
