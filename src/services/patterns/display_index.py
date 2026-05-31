"""Helpers for dense user-facing pattern numbering."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import PatternRepository
from src.utils.async_utils import resolve_awaitable


@dataclass(slots=True)
class PatternDisplayIndexResolver:
    """Resolve dense per-thread display numbers in creation order."""

    pattern_repository: PatternRepository

    async def build_index_map(self, thread_id: int) -> dict[int, int]:
        return {
            pattern.pattern_id: display_index
            for display_index, pattern in enumerate(
                await resolve_awaitable(self.pattern_repository.list_patterns_for_thread(thread_id)),
                start=1,
            )
        }

    async def resolve(self, *, thread_id: int, pattern_id: int) -> int | None:
        return (await self.build_index_map(thread_id)).get(pattern_id)
