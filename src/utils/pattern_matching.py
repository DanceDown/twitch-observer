"""Helpers for evaluating ping and regex patterns against Twitch chat messages."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from src.events.twitch_events import TwitchChatMessageEvent


class PatternContentRule(Protocol):
    """Minimal rule shape needed for message-content pattern checks."""

    regex: str
    is_regex: bool
    case_sensitive: bool


@dataclass(slots=True)
class PatternCompileCache:
    """Small reusable compile cache for hot-path chat pattern checks."""

    max_entries: int = 512
    _compile_cached: Callable[..., re.Pattern[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build either an LRU-backed compiler or a direct compiler for disabled caches."""
        self.max_entries = max(0, self.max_entries)
        if self.max_entries > 0:
            self._compile_cached = lru_cache(maxsize=self.max_entries)(self.compile_pattern)
        else:
            self._compile_cached = self.compile_pattern

    @staticmethod
    def compile_pattern(regex: str, *, is_regex: bool, case_sensitive: bool) -> re.Pattern[str]:
        """Compile a regex directly or wrap a plain word in word boundaries."""
        flags = 0 if case_sensitive else re.IGNORECASE
        source = regex if is_regex else rf"\b{re.escape(regex)}\b"
        return re.compile(source, flags)

    def get(self, pattern: PatternContentRule) -> re.Pattern[str]:
        """Return a compiled pattern from cache when caching is enabled."""
        return self._compile_cached(pattern.regex, is_regex=pattern.is_regex, case_sensitive=pattern.case_sensitive)

    def cache_info(self) -> object | None:
        """Expose LRU stats for diagnostics when the cache is enabled."""
        cache_info = getattr(self._compile_cached, "cache_info", None)
        return None if cache_info is None else cache_info()


def matches_pattern_content(
    pattern: PatternContentRule,
    event: TwitchChatMessageEvent,
    *,
    compile_cache: PatternCompileCache | None = None,
) -> bool:
    """Return whether only the message content matches one stored pattern."""
    content = normalize_message_content_for_pattern_matching(event.content)
    compiled = (
        compile_cache.get(pattern)
        if compile_cache is not None
        else PatternCompileCache.compile_pattern(
            pattern.regex,
            is_regex=pattern.is_regex,
            case_sensitive=pattern.case_sensitive,
        )
    )
    return compiled.search(content) is not None


def normalize_message_content_for_pattern_matching(content: str) -> str:
    """Remove duplicate-message suffix chars that some chat clients append at the end."""
    end = len(content)
    while end > 0:
        char = content[end - 1]
        if char.isspace() or unicodedata.category(char) == "Cf":
            end -= 1
            continue
        break
    return content[:end]


def is_sender_sub(event: TwitchChatMessageEvent) -> bool:
    """Infer subscriber state from Twitch IRC badges."""
    badges = event.raw_tags.get("badges", "")
    parts = [badge.split("/", 1)[0] for badge in badges.split(",") if badge]
    return "subscriber" in parts or "founder" in parts
