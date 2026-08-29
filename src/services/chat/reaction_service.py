"""Shared Twitch chat reaction orchestration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from src.events.twitch_events import TwitchChatMessageEvent
from src.services.chat_delivery_context import ChatMessageCompletionNotifier, get_current_chat_message_sequence

from .matcher import ChatPatternMatch, ChatPatternMatcher

logger = logging.getLogger(__name__)


class TrackingMatchHandler(Protocol):
    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None: ...


class ReplyMatchHandler(Protocol):
    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None: ...


@dataclass(slots=True)
class ChatMessageReactionService:
    """Evaluate one chat message once, then dispatch tracking or auto-reply work."""

    matcher: ChatPatternMatcher
    tracking: TrackingMatchHandler
    replies: ReplyMatchHandler
    completion_notifier: ChatMessageCompletionNotifier | None = None

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        sequence = get_current_chat_message_sequence()
        matches: tuple[ChatPatternMatch, ...] = ()
        try:
            matches = await self.matcher.find_matches(event)
            for match in matches:
                await self._reserve_match_delivery_safely(match)
        finally:
            if sequence is not None and self.completion_notifier is not None:
                await self._complete_routing_safely(sequence)
        if not matches:
            return
        await asyncio.gather(*(self._handle_match_safely(event, match) for match in matches))

    async def _reserve_match_delivery_safely(self, match: ChatPatternMatch) -> None:
        handler = self.tracking if match.reply is None else self.replies
        reserve = getattr(handler, "reserve_match_delivery", None)
        if reserve is None:
            return
        try:
            await reserve(match)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to reserve chat match delivery thread_id=%s pattern_id=%s.",
                match.thread.thread_id,
                match.pattern.pattern_id,
            )

    async def _complete_routing_safely(self, sequence: int) -> None:
        if self.completion_notifier is None:
            return
        try:
            await self.completion_notifier.complete_message_routing(sequence)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to complete chat message routing sequence=%s.", sequence)

    async def _handle_match_safely(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        try:
            if match.reply is None:
                await self.tracking.handle_match(event, match)
                return
            await self.replies.handle_match(event, match)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to handle chat match thread_id=%s pattern_id=%s message_id=%s.",
                match.thread.thread_id,
                match.pattern.pattern_id,
                event.message_id,
            )
