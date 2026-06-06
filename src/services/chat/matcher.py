"""Shared chat-pattern matching used by Twitch message reactions."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    ChannelRecord,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ThreadRecord,
)
from src.events.event_types import TwitchChatMessageEvent
from src.utils.pattern_matching import is_sender_sub, matches_pattern_content


@dataclass(slots=True, frozen=True)
class ChatPatternMatch:
    """First matching pattern for one thread plus its attached enabled reply, if any."""

    thread: ThreadRecord
    source_channel: ChannelRecord | None
    pattern: PatternRecord
    reply: ReplyRecord | None
    explicit_user_scope_match: bool = False


@dataclass(slots=True)
class ChatPatternMatcher:
    """Resolve the first matching pattern per interested thread for one chat message."""

    pattern_repository: PatternRepository

    async def find_matches(self, event: TwitchChatMessageEvent) -> tuple[ChatPatternMatch, ...]:
        if not event.broadcaster_id or not event.author_id:
            return ()

        candidates = await self.pattern_repository.list_chat_match_candidates(
            broadcaster_id=event.broadcaster_id,
            author_id=event.author_id,
            sender_is_sub=is_sender_sub(event),
        )
        matches: list[ChatPatternMatch] = []
        matched_thread_ids: set[int] = set()
        for candidate in candidates:
            if candidate.thread.thread_id in matched_thread_ids:
                continue
            if not matches_pattern_content(candidate.pattern, event):
                continue
            matches.append(
                ChatPatternMatch(
                    thread=candidate.thread,
                    source_channel=candidate.source_channel,
                    pattern=candidate.pattern,
                    reply=candidate.reply,
                    explicit_user_scope_match=candidate.explicit_user_scope_match,
                )
            )
            matched_thread_ids.add(candidate.thread.thread_id)
        return tuple(matches)
