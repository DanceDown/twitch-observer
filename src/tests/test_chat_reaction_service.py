from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.database.records import ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from src.events.event_types import TwitchChatMessageEvent
from src.services.chat import ChatMessageReactionService, ChatPatternMatch, ChatPatternMatcher


@dataclass
class _ThreadRepository:
    thread: ThreadRecord

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        return self.thread if self.thread.thread_id == thread_id else None


@dataclass
class _ChannelRepository:
    channel: ChannelRecord

    async def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        return [self.channel.thread_id] if self.channel.twitch_channel_id == twitch_channel_id else []

    async def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        if self.channel.thread_id == thread_id and self.channel.twitch_channel_id == twitch_channel_id:
            return self.channel
        return None


@dataclass
class _PatternRepository:
    patterns: list[PatternRecord]

    async def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        return [pattern for pattern in self.patterns if pattern.thread_id == thread_id]


@dataclass
class _ReplyRepository:
    replies: list[ReplyRecord] = field(default_factory=list)

    async def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool) -> list[ReplyRecord]:
        return [reply for reply in self.replies if reply.thread_id == thread_id]


def _thread() -> ThreadRecord:
    return ThreadRecord(thread_id=1, owner_id=1, discord_channel_id=99, enabled=True, color=None)


def _pattern(pattern_id: int, regex: str) -> PatternRecord:
    return PatternRecord(
        thread_id=1,
        pattern_id=pattern_id,
        regex=regex,
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        notify=True,
        priority=pattern_id,
    )


@pytest.mark.asyncio
async def test_chat_pattern_matcher_returns_first_match_with_enabled_reply() -> None:
    matcher = ChatPatternMatcher(
        thread_repository=_ThreadRepository(_thread()),  # type: ignore[arg-type]
        channel_repository=_ChannelRepository(ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)),  # type: ignore[arg-type]
        pattern_repository=_PatternRepository([_pattern(1, "miss"), _pattern(2, "hello")]),  # type: ignore[arg-type]
        reply_repository=_ReplyRepository(
            replies=[
                ReplyRecord(thread_id=1, pattern_id=2, reply_message="hi", reply_as_reply=False, disabled=False),
            ]
        ),  # type: ignore[arg-type]
    )

    matches = await matcher.find_matches(
        TwitchChatMessageEvent(
            channel_login="chan",
            broadcaster_id="42",
            author_login="alice",
            author_id="7",
            content="hello world",
            message_id="m-1",
        )
    )

    assert len(matches) == 1
    assert matches[0].pattern.pattern_id == 2
    assert matches[0].reply is not None
    assert matches[0].reply.reply_message == "hi"


@dataclass
class _StaticMatcher:
    matches: tuple[ChatPatternMatch, ...]

    async def find_matches(self, event: TwitchChatMessageEvent) -> tuple[ChatPatternMatch, ...]:
        return self.matches


@dataclass
class _TrackingHandler:
    calls: list[int] = field(default_factory=list)

    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        self.calls.append(match.pattern.pattern_id)


@dataclass
class _ReplyHandler:
    calls: list[int] = field(default_factory=list)

    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        self.calls.append(match.pattern.pattern_id)


@pytest.mark.asyncio
async def test_chat_reaction_service_routes_tracking_and_reply_matches() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    tracking = _TrackingHandler()
    replies = _ReplyHandler()
    service = ChatMessageReactionService(
        matcher=_StaticMatcher(
            (
                ChatPatternMatch(thread=thread, source_channel=source_channel, pattern=_pattern(1, "hello"), reply=None),
                ChatPatternMatch(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(2, "world"),
                    reply=ReplyRecord(thread_id=1, pattern_id=2, reply_message="pong", reply_as_reply=False, disabled=False),
                ),
            )
        ),  # type: ignore[arg-type]
        tracking=tracking,
        replies=replies,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="chan",
            broadcaster_id="42",
            author_login="alice",
            author_id="7",
            content="hello world",
            message_id="m-1",
        )
    )

    assert tracking.calls == [1]
    assert replies.calls == [2]
