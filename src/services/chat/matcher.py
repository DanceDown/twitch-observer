"""Shared chat-pattern matching used by Twitch message reactions."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    ChannelRecord,
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
)
from src.events.event_types import TwitchChatMessageEvent
from src.services.twitch_runtime import expand_pattern_for_tracked_users, offline_state_allows
from src.utils.pattern_matching import matches_pattern


@dataclass(slots=True, frozen=True)
class ChatPatternMatch:
    """First matching pattern for one thread plus its attached enabled reply, if any."""

    thread: ThreadRecord
    source_channel: ChannelRecord | None
    pattern: PatternRecord
    reply: ReplyRecord | None


@dataclass(slots=True)
class ChatPatternMatcher:
    """Resolve the first matching pattern per interested thread for one chat message."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository | None = None
    tracked_user_repository: TrackedUserRepository | None = None

    async def find_matches(self, event: TwitchChatMessageEvent) -> tuple[ChatPatternMatch, ...]:
        if not event.broadcaster_id or not event.author_id:
            return ()

        thread_ids = await self.channel_repository.list_thread_ids_by_twitch_channel_id(event.broadcaster_id)
        matches: list[ChatPatternMatch] = []
        for thread_id in thread_ids:
            thread = await self.thread_repository.get_by_thread_id(thread_id)
            if thread is None or not thread.enabled:
                continue

            source_channel = await self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, event.broadcaster_id)
            live_status = None if source_channel is None else source_channel.is_live
            reply_map = await self._load_enabled_reply_map(thread.thread_id)
            patterns = await self.pattern_repository.list_active_patterns_for_thread(thread.thread_id)
            for pattern in patterns:
                effective_pattern = await expand_pattern_for_tracked_users(
                    pattern,
                    thread_id=thread.thread_id,
                    tracked_user_repository=self.tracked_user_repository,
                )
                if not matches_pattern(effective_pattern, event):
                    continue
                if not offline_state_allows(effective_pattern, live_status):
                    continue
                matches.append(
                    ChatPatternMatch(
                        thread=thread,
                        source_channel=source_channel,
                        pattern=effective_pattern,
                        reply=reply_map.get(effective_pattern.pattern_id),
                    )
                )
                break
        return tuple(matches)

    async def _load_enabled_reply_map(self, thread_id: int) -> dict[int, ReplyRecord]:
        if self.reply_repository is None:
            return {}
        replies = await self.reply_repository.list_replies_for_thread(thread_id, include_disabled=True)
        return {reply.pattern_id: reply for reply in replies if not reply.disabled}
