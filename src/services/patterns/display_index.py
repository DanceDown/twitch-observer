"""Helpers for dense user-facing pattern numbering."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import PatternRepository


@dataclass(slots=True)
class PatternDisplayIndexResolver:
    """Resolve dense per-thread display numbers for stable internal pattern IDs."""

    pattern_repository: PatternRepository

    def build_index_map(self, thread_id: int) -> dict[int, int]:
        return {
            pattern.pattern_id: display_index
            for display_index, pattern in enumerate(
                self.pattern_repository.list_patterns_for_thread(thread_id),
                start=1,
            )
        }

    def resolve(self, *, thread_id: int, pattern_id: int) -> int | None:
        return self.build_index_map(thread_id).get(pattern_id)
