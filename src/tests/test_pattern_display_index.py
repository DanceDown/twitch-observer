from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import PatternRecord, PatternRepository
from src.services.patterns.display_index import PatternDisplayIndexResolver


def _pattern(*, pattern_id: int) -> PatternRecord:
    return PatternRecord(
        thread_id=1,
        pattern_id=pattern_id,
        regex=f"pattern-{pattern_id}",
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
        priority=None,
        reply_message=None,
        reply_as_reply=False,
    )


@dataclass
class InMemoryPatternRepository(PatternRepository):
    patterns_by_thread: dict[int, list[PatternRecord]] = field(default_factory=dict)

    def list_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        return list(self.patterns_by_thread.get(thread_id, ()))


def test_display_indexes_are_dense_even_when_internal_pattern_ids_have_gaps() -> None:
    repository = InMemoryPatternRepository(patterns_by_thread={1: [_pattern(pattern_id=1), _pattern(pattern_id=3)]})
    resolver = PatternDisplayIndexResolver(repository)

    assert resolver.build_index_map(1) == {1: 1, 3: 2}
    assert resolver.resolve(thread_id=1, pattern_id=3) == 2
