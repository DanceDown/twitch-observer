"""Shared chat-pattern matching used by Twitch message reactions."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    ChannelRecord,
    PatternRecord,
    ChatPatternSeedRecord,
    PatternRepository,
    ReplyRecord,
    ThreadRecord,
)
from src.events.twitch_events import TwitchChatMessageEvent
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

        seeds = await self.pattern_repository.list_chat_match_seeds(
            broadcaster_id=event.broadcaster_id,
            author_id=event.author_id,
            sender_is_sub=is_sender_sub(event),
        )
        matched_seeds: list[ChatPatternSeedRecord] = []
        matched_thread_ids: set[int] = set()
        for seed in seeds:
            if seed.thread_id in matched_thread_ids:
                continue
            if not matches_pattern_content(seed, event):
                continue
            matched_seeds.append(seed)
            matched_thread_ids.add(seed.thread_id)
        if not matched_seeds:
            return ()

        candidates = await self.pattern_repository.hydrate_chat_match_candidates(
            broadcaster_id=event.broadcaster_id,
            seeds=tuple(matched_seeds),
        )
        return tuple(
            ChatPatternMatch(
                thread=candidate.thread,
                source_channel=candidate.source_channel,
                pattern=candidate.pattern,
                reply=candidate.reply,
                explicit_user_scope_match=candidate.explicit_user_scope_match,
            )
            for candidate in candidates
        )
