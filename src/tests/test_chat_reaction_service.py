from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.database.records import ChatPatternCandidateRecord, ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from src.events.twitch_events import TwitchChatMessageEvent
from src.services.chat import ChatMessageReactionService, ChatPatternMatch, ChatPatternMatcher


@dataclass
class _BatchPatternRepository:
    candidates: list[ChatPatternCandidateRecord]

    async def list_chat_match_candidates(
        self,
        *,
        broadcaster_id: str,
        author_id: str,
        sender_is_sub: bool,
    ) -> list[ChatPatternCandidateRecord]:
        _ = (broadcaster_id, author_id, sender_is_sub)
        return list(self.candidates)


def _thread() -> ThreadRecord:
    return ThreadRecord(thread_id=1, owner_id=1, discord_channel_id=99, enabled=True, color=None)


def _pattern(
    pattern_id: int,
    regex: str,
    *,
    is_regex: bool = False,
    case_sensitive: bool = False,
) -> PatternRecord:
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
        is_regex=is_regex,
        case_sensitive=case_sensitive,
        color=None,
        disabled=False,
        priority=pattern_id,
    )


@pytest.mark.asyncio
async def test_chat_pattern_matcher_returns_first_match_with_enabled_reply() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    matcher = ChatPatternMatcher(
        pattern_repository=_BatchPatternRepository(
            candidates=[
                ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(1, "miss"),
                    reply=None,
                    explicit_user_scope_match=False,
                ),
                ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(2, "hello"),
                    reply=ReplyRecord(
                        thread_id=1,
                        pattern_id=2,
                        reply_message="hi",
                        reply_as_reply=False,
                        disabled=False,
                    ),
                    explicit_user_scope_match=False,
                ),
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


@pytest.mark.asyncio
async def test_chat_pattern_matcher_uses_batched_candidates_and_keeps_explicit_user_match() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    matcher = ChatPatternMatcher(
        pattern_repository=_BatchPatternRepository(
            candidates=[
                ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(1, "miss"),
                    reply=None,
                    explicit_user_scope_match=False,
                ),
                ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(2, "hello"),
                    reply=ReplyRecord(thread_id=1, pattern_id=2, reply_message="pong", reply_as_reply=False, disabled=False),
                    explicit_user_scope_match=True,
                ),
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
    assert matches[0].explicit_user_scope_match is True


@pytest.mark.asyncio
async def test_chat_pattern_matcher_ignores_trailing_spaces_from_duplicate_message_suffixes() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    matcher = ChatPatternMatcher(
        pattern_repository=_BatchPatternRepository(
            candidates=[
                ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(1, r"^hello$", is_regex=True),
                    reply=None,
                    explicit_user_scope_match=False,
                )
            ]
        ),  # type: ignore[arg-type]
    )

    matches = await matcher.find_matches(
        TwitchChatMessageEvent(
            channel_login="chan",
            broadcaster_id="42",
            author_login="alice",
            author_id="7",
            content="hello   ",
            message_id="m-1",
        )
    )

    assert len(matches) == 1
    assert matches[0].pattern.pattern_id == 1


@pytest.mark.asyncio
async def test_chat_pattern_matcher_ignores_trailing_invisible_duplicate_suffixes() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    matcher = ChatPatternMatcher(
        pattern_repository=_BatchPatternRepository(
            candidates=[
                ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(1, r"^hello$", is_regex=True),
                    reply=None,
                    explicit_user_scope_match=False,
                )
            ]
        ),  # type: ignore[arg-type]
    )

    matches = await matcher.find_matches(
        TwitchChatMessageEvent(
            channel_login="chan",
            broadcaster_id="42",
            author_login="alice",
            author_id="7",
            content="hello\u200b",
            message_id="m-1",
        )
    )

    assert len(matches) == 1
    assert matches[0].pattern.pattern_id == 1


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
