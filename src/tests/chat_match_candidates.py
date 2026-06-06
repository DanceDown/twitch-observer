from __future__ import annotations

from src.database.connection import (
    ChatPatternCandidateRecord,
    ChannelRecord,
    ChannelRepository,
    PatternRecord,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
)


async def build_chat_match_candidates(
    *,
    patterns: list[PatternRecord],
    thread_repository: ThreadRepository | None,
    channel_repository: ChannelRepository | None,
    reply_repository: ReplyRepository | None,
    tracked_user_repository: TrackedUserRepository | None,
    broadcaster_id: str,
    author_id: str,
    sender_is_sub: bool,
) -> list[ChatPatternCandidateRecord]:
    rows: list[ChatPatternCandidateRecord] = []
    for pattern in sorted(patterns, key=lambda row: (row.thread_id, -row.priority, row.pattern_id)):
        if pattern.disabled:
            continue
        thread = await _get_enabled_thread(thread_repository=thread_repository, thread_id=pattern.thread_id)
        if thread is None:
            continue
        channel = await _get_source_channel(
            channel_repository=channel_repository,
            thread_id=pattern.thread_id,
            broadcaster_id=broadcaster_id,
        )
        if channel is None or not _channel_scope_allows(pattern=pattern, broadcaster_id=broadcaster_id):
            continue
        explicit_user_scope_match = pattern.user_scope_mode == "only_selected" and author_id in pattern.user_scope_ids
        if not await _user_scope_allows(
            pattern=pattern,
            thread_id=pattern.thread_id,
            author_id=author_id,
            tracked_user_repository=tracked_user_repository,
        ):
            continue
        if pattern.sub_state == "subs" and not sender_is_sub:
            continue
        if pattern.sub_state == "non_subs" and sender_is_sub:
            continue
        if not _offline_state_allows(pattern=pattern, live_status=channel.is_live):
            continue
        rows.append(
            ChatPatternCandidateRecord(
                thread=thread,
                source_channel=channel,
                pattern=pattern,
                reply=await _get_enabled_reply(
                    reply_repository=reply_repository,
                    thread_id=pattern.thread_id,
                    pattern_id=pattern.pattern_id,
                ),
                explicit_user_scope_match=explicit_user_scope_match,
            )
        )
    return rows


async def _get_enabled_thread(
    *,
    thread_repository: ThreadRepository | None,
    thread_id: int,
) -> ThreadRecord | None:
    if thread_repository is None:
        raise AssertionError("thread_repository is required for list_chat_match_candidates in tests")
    thread = await thread_repository.get_by_thread_id(thread_id)
    if thread is None or not thread.enabled:
        return None
    return thread


async def _get_source_channel(
    *,
    channel_repository: ChannelRepository | None,
    thread_id: int,
    broadcaster_id: str,
) -> ChannelRecord | None:
    if channel_repository is None:
        raise AssertionError("channel_repository is required for list_chat_match_candidates in tests")
    return await channel_repository.get_by_thread_and_twitch_channel(thread_id, broadcaster_id)


def _channel_scope_allows(*, pattern: PatternRecord, broadcaster_id: str) -> bool:
    if pattern.channel_scope_mode == "only_selected":
        return broadcaster_id in pattern.channel_scope_ids
    if pattern.channel_scope_mode == "all_except_selected":
        return broadcaster_id not in pattern.channel_scope_ids
    return True


async def _user_scope_allows(
    *,
    pattern: PatternRecord,
    thread_id: int,
    author_id: str,
    tracked_user_repository: TrackedUserRepository | None,
) -> bool:
    if pattern.user_scope_mode == "all_users":
        return True
    if pattern.user_scope_mode == "only_selected":
        return author_id in pattern.user_scope_ids
    if pattern.user_scope_mode == "all_except_selected":
        return author_id not in pattern.user_scope_ids
    if tracked_user_repository is None:
        raise AssertionError("tracked_user_repository is required for tracked user scope tests")
    tracked = await tracked_user_repository.get_by_thread_and_twitch_user(thread_id, author_id)
    if pattern.user_scope_mode == "all_tracked":
        return tracked is not None
    if pattern.user_scope_mode == "all_tracked_except_selected":
        return tracked is not None and author_id not in pattern.user_scope_ids
    return False


def _offline_state_allows(*, pattern: PatternRecord, live_status: bool | None) -> bool:
    if pattern.offline_state == "both" or live_status is None:
        return True
    if pattern.offline_state == "online":
        return live_status
    if pattern.offline_state == "offline":
        return not live_status
    return False


async def _get_enabled_reply(
    *,
    reply_repository: ReplyRepository | None,
    thread_id: int,
    pattern_id: int,
) -> ReplyRecord | None:
    if reply_repository is None:
        return None
    reply = await reply_repository.get_by_pattern(thread_id=thread_id, pattern_id=pattern_id)
    if reply is None or reply.disabled:
        return None
    return reply
