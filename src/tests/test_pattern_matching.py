from __future__ import annotations

from types import SimpleNamespace

from src.events.twitch_events import TwitchChatMessageEvent
from src.utils.pattern_matching import PatternCompileCache, matches_pattern_content


def _event(content: str) -> TwitchChatMessageEvent:
    return TwitchChatMessageEvent(
        channel_login="chan",
        author_login="alice",
        author_id="7",
        broadcaster_id="42",
        content=content,
    )


def test_pattern_compile_cache_reuses_compiled_regex_objects() -> None:
    cache = PatternCompileCache(max_entries=8)

    rule = SimpleNamespace(regex=r"^hello$", is_regex=True, case_sensitive=False)
    cache.get(rule)
    cache.get(rule)
    info = cache.cache_info()

    assert info is not None
    assert info.hits == 1
    assert info.misses == 1


def test_pattern_compile_cache_can_be_disabled() -> None:
    cache = PatternCompileCache(max_entries=0)

    assert cache.cache_info() is None

    assert matches_pattern_content(SimpleNamespace(regex="hello", is_regex=False, case_sensitive=False), _event("hello"), compile_cache=cache) is True


def test_matches_pattern_content_uses_compile_cache_for_word_patterns() -> None:
    cache = PatternCompileCache(max_entries=8)
    pattern = SimpleNamespace(regex="hello", is_regex=False, case_sensitive=False)

    assert matches_pattern_content(pattern, _event("hello world"), compile_cache=cache) is True
    assert matches_pattern_content(pattern, _event("goodbye world"), compile_cache=cache) is False
