"""Shared Twitch chat reaction orchestration."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from src.events.twitch_events import TwitchChatMessageEvent

from .matcher import ChatPatternMatch, ChatPatternMatcher


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

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        for match in await self.matcher.find_matches(event):
            if match.reply is None:
                await self.tracking.handle_match(event, match)
                continue
            await self.replies.handle_match(event, match)
