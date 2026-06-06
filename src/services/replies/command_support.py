"""Shared helpers for reply command handling."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import PatternRepository
from src.localization import Localizer
from src.services.patterns.display_index import PatternDisplayIndexResolver


@dataclass(slots=True)
class ReplyCommandSupport:
    """Localized helpers and resolvers for reply commands."""

    pattern_repository: PatternRepository
    localizer: Localizer
    _display_index: PatternDisplayIndexResolver = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._display_index = PatternDisplayIndexResolver(self.pattern_repository)

    async def display_index(self, thread_id: int, pattern_id: int) -> int | None:
        return await self._display_index.resolve(thread_id=thread_id, pattern_id=pattern_id)

    def text(self, key: str, *, language: str, **placeholders: object) -> str:
        return self.localizer.text(key, language=language, **placeholders)
