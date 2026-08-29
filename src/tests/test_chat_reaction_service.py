from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.database.records import ChatPatternCandidateRecord, ChatPatternSeedRecord, ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from src.events.twitch_events import TwitchChatMessageEvent
from src.services.chat import ChatMessageReactionService, ChatPatternMatch, ChatPatternMatcher
from src.services.chat_delivery_context import bind_chat_message_sequence, reset_chat_message_sequence


@dataclass
class _BatchPatternRepository:
    seeds: list[ChatPatternSeedRecord]
    hydrated_candidates: dict[tuple[int, int], ChatPatternCandidateRecord]
    hydrated_calls: list[tuple[tuple[int, int], ...]] = field(default_factory=list)

    async def list_chat_match_seeds(
        self,
        *,
        broadcaster_id: str,
        author_id: str,
        sender_is_sub: bool,
    ) -> list[ChatPatternSeedRecord]:
        _ = (broadcaster_id, author_id, sender_is_sub)
        return list(self.seeds)

    async def hydrate_chat_match_candidates(
        self,
        *,
        broadcaster_id: str,
        seeds: tuple[ChatPatternSeedRecord, ...],
    ) -> list[ChatPatternCandidateRecord]:
        _ = broadcaster_id
        self.hydrated_calls.append(tuple((seed.thread_id, seed.pattern_id) for seed in seeds))
        return [self.hydrated_candidates[(seed.thread_id, seed.pattern_id)] for seed in seeds]


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


def _seed(
    pattern_id: int,
    regex: str,
    *,
    is_regex: bool = False,
    case_sensitive: bool = False,
    explicit_user_scope_match: bool = False,
) -> ChatPatternSeedRecord:
    return ChatPatternSeedRecord(
        thread_id=1,
        pattern_id=pattern_id,
        regex=regex,
        is_regex=is_regex,
        case_sensitive=case_sensitive,
        priority=pattern_id,
        explicit_user_scope_match=explicit_user_scope_match,
    )


@pytest.mark.asyncio
async def test_chat_pattern_matcher_returns_first_match_with_enabled_reply() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    matcher = ChatPatternMatcher(
        pattern_repository=_BatchPatternRepository(
            seeds=[
                _seed(1, "miss"),
                _seed(2, "hello"),
            ],
            hydrated_candidates={
                (1, 2): ChatPatternCandidateRecord(
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
                )
            },
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
    assert matcher.pattern_repository.hydrated_calls == [((1, 2),)]


@pytest.mark.asyncio
async def test_chat_pattern_matcher_uses_batched_candidates_and_keeps_explicit_user_match() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    matcher = ChatPatternMatcher(
        pattern_repository=_BatchPatternRepository(
            seeds=[
                _seed(1, "miss"),
                _seed(2, "hello", explicit_user_scope_match=True),
            ],
            hydrated_candidates={
                (1, 2): ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(2, "hello"),
                    reply=ReplyRecord(thread_id=1, pattern_id=2, reply_message="pong", reply_as_reply=False, disabled=False),
                    explicit_user_scope_match=True,
                )
            },
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
    assert matcher.pattern_repository.hydrated_calls == [((1, 2),)]


@pytest.mark.asyncio
async def test_chat_pattern_matcher_ignores_trailing_spaces_from_duplicate_message_suffixes() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    matcher = ChatPatternMatcher(
        pattern_repository=_BatchPatternRepository(
            seeds=[
                _seed(1, r"^hello$", is_regex=True),
            ],
            hydrated_candidates={
                (1, 1): ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(1, r"^hello$", is_regex=True),
                    reply=None,
                    explicit_user_scope_match=False,
                )
            },
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
    assert matcher.pattern_repository.hydrated_calls == [((1, 1),)]


@pytest.mark.asyncio
async def test_chat_pattern_matcher_ignores_trailing_invisible_duplicate_suffixes() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    matcher = ChatPatternMatcher(
        pattern_repository=_BatchPatternRepository(
            seeds=[
                _seed(1, r"^hello$", is_regex=True),
            ],
            hydrated_candidates={
                (1, 1): ChatPatternCandidateRecord(
                    thread=thread,
                    source_channel=source_channel,
                    pattern=_pattern(1, r"^hello$", is_regex=True),
                    reply=None,
                    explicit_user_scope_match=False,
                )
            },
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
    assert matcher.pattern_repository.hydrated_calls == [((1, 1),)]


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
class _ReservingTrackingHandler:
    events: list[str] = field(default_factory=list)

    async def reserve_match_delivery(self, match: ChatPatternMatch) -> None:
        self.events.append(f"reserve:{match.pattern.pattern_id}")

    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        self.events.append(f"handle:{match.pattern.pattern_id}")


@dataclass
class _ReplyHandler:
    calls: list[int] = field(default_factory=list)

    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        self.calls.append(match.pattern.pattern_id)


@dataclass
class _BlockingTrackingHandler:
    expected_calls: int
    release: asyncio.Event
    all_started: asyncio.Event
    calls: list[int] = field(default_factory=list)

    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        self.calls.append(match.pattern.pattern_id)
        if len(self.calls) >= self.expected_calls:
            self.all_started.set()
        await self.release.wait()


@dataclass
class _FailingTrackingHandler:
    failing_pattern_id: int
    calls: list[int] = field(default_factory=list)

    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        self.calls.append(match.pattern.pattern_id)
        if match.pattern.pattern_id == self.failing_pattern_id:
            raise RuntimeError("boom")


@dataclass
class _RoutingNotifier:
    completed_routing: list[int] = field(default_factory=list)

    async def reserve_message(self, sequence: int) -> None:
        _ = sequence

    async def complete_message_routing(self, sequence: int) -> None:
        self.completed_routing.append(sequence)

    async def complete_message(self, sequence: int) -> None:
        _ = sequence


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


@pytest.mark.asyncio
async def test_chat_reaction_service_reserves_matches_before_handling() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    tracking = _ReservingTrackingHandler()
    routing_notifier = _RoutingNotifier()
    service = ChatMessageReactionService(
        matcher=_StaticMatcher(
            (
                ChatPatternMatch(thread=thread, source_channel=source_channel, pattern=_pattern(1, "hello"), reply=None),
                ChatPatternMatch(thread=thread, source_channel=source_channel, pattern=_pattern(2, "world"), reply=None),
            )
        ),  # type: ignore[arg-type]
        tracking=tracking,
        replies=_ReplyHandler(),
        completion_notifier=routing_notifier,
    )

    token = bind_chat_message_sequence(9)
    try:
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
    finally:
        reset_chat_message_sequence(token)

    assert tracking.events == ["reserve:1", "reserve:2", "handle:1", "handle:2"]
    assert routing_notifier.completed_routing == [9]


@pytest.mark.asyncio
async def test_chat_reaction_service_handles_matches_in_parallel() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    release = asyncio.Event()
    all_started = asyncio.Event()
    tracking = _BlockingTrackingHandler(expected_calls=2, release=release, all_started=all_started)
    service = ChatMessageReactionService(
        matcher=_StaticMatcher(
            (
                ChatPatternMatch(thread=thread, source_channel=source_channel, pattern=_pattern(1, "hello"), reply=None),
                ChatPatternMatch(thread=thread, source_channel=source_channel, pattern=_pattern(2, "world"), reply=None),
            )
        ),  # type: ignore[arg-type]
        tracking=tracking,
        replies=_ReplyHandler(),
    )

    task = asyncio.create_task(
        service.handle_chat_message(
            TwitchChatMessageEvent(
                channel_login="chan",
                broadcaster_id="42",
                author_login="alice",
                author_id="7",
                content="hello world",
                message_id="m-1",
            )
        )
    )
    await asyncio.wait_for(all_started.wait(), timeout=1)

    assert task.done() is False
    release.set()
    await asyncio.wait_for(task, timeout=1)
    assert tracking.calls == [1, 2]


@pytest.mark.asyncio
async def test_chat_reaction_service_keeps_handling_other_matches_after_one_failure() -> None:
    thread = _thread()
    source_channel = ChannelRecord(thread_id=1, twitch_channel_id="42", color=None)
    tracking = _FailingTrackingHandler(failing_pattern_id=1)
    service = ChatMessageReactionService(
        matcher=_StaticMatcher(
            (
                ChatPatternMatch(thread=thread, source_channel=source_channel, pattern=_pattern(1, "hello"), reply=None),
                ChatPatternMatch(thread=thread, source_channel=source_channel, pattern=_pattern(2, "world"), reply=None),
            )
        ),  # type: ignore[arg-type]
        tracking=tracking,
        replies=_ReplyHandler(),
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

    assert tracking.calls == [1, 2]
