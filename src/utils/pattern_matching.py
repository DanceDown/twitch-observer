from __future__ import annotations

"""Helpers for evaluating ping and regex patterns against Twitch chat messages."""

import re

from src.database.connection import PatternRecord
from src.events.event_types import TwitchChatMessageEvent


def matches_pattern(pattern: PatternRecord, event: TwitchChatMessageEvent) -> bool:
    """Return whether a Twitch message matches a stored pattern."""
    if not _matches_channel_scope(pattern, event):
        return False
    if not _matches_user_scope(pattern, event):
        return False
    if not _matches_sub_state(pattern.sub_state, event):
        return False

    flags = 0 if pattern.case_sensitive else re.IGNORECASE
    if pattern.is_regex:
        return re.search(pattern.regex, event.content, flags) is not None

    escaped = re.escape(pattern.regex)
    return re.search(rf"\b{escaped}\b", event.content, flags) is not None


def is_sender_sub(event: TwitchChatMessageEvent) -> bool:
    """Infer subscriber state from Twitch IRC badges."""
    badges = event.raw_tags.get("badges", "")
    parts = [badge.split("/", 1)[0] for badge in badges.split(",") if badge]
    return "subscriber" in parts or "founder" in parts


def _matches_sub_state(sub_state: str, event: TwitchChatMessageEvent) -> bool:
    sender_is_sub = is_sender_sub(event)
    if sub_state == "all":
        return True
    if sub_state == "non_subs":
        return not sender_is_sub
    if sub_state == "subs":
        return sender_is_sub
    return False


def _matches_channel_scope(pattern: PatternRecord, event: TwitchChatMessageEvent) -> bool:
    broadcaster_id = event.broadcaster_id
    if broadcaster_id is None:
        return False
    if pattern.channel_scope_mode == "all_tracked":
        return True
    if pattern.channel_scope_mode == "only_selected":
        return broadcaster_id in pattern.channel_scope_ids
    if pattern.channel_scope_mode == "all_except_selected":
        return broadcaster_id not in pattern.channel_scope_ids
    return False


def _matches_user_scope(pattern: PatternRecord, event: TwitchChatMessageEvent) -> bool:
    author_id = event.author_id
    if author_id is None:
        return False
    if pattern.user_scope_mode == "all_users":
        return True
    if pattern.user_scope_mode == "only_selected":
        return author_id in pattern.user_scope_ids
    if pattern.user_scope_mode == "all_except_selected":
        return author_id not in pattern.user_scope_ids
    if pattern.user_scope_mode == "all_tracked":
        return author_id in pattern.user_scope_ids
    if pattern.user_scope_mode == "all_tracked_except_selected":
        return author_id in pattern.user_scope_ids
    return False
