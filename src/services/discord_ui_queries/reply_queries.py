"""Reply query service for Discord UI flows."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import ReplyRepository, ThreadRecord, ThreadRepository

from .pattern_queries import PatternQueryService
from .presentations import ReplyPresentation
from .shared import get_thread_for_channel


@dataclass(slots=True)
class ReplyQueryService:
    thread_repository: ThreadRepository
    reply_repository: ReplyRepository
    pattern_queries: PatternQueryService

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await get_thread_for_channel(self.thread_repository, discord_channel_id)

    async def list_replies(self, discord_channel_id: int) -> list[ReplyPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []

        pattern_map = {item.pattern.pattern_id: item for item in await self.pattern_queries.list_patterns(discord_channel_id)}
        presentations: list[ReplyPresentation] = []
        for reply in await self.reply_repository.list_replies_for_thread(thread.thread_id, include_disabled=True):
            pattern = pattern_map.get(reply.pattern_id)
            if pattern is None:
                continue
            presentations.append(ReplyPresentation(reply=reply, pattern=pattern))
        presentations.sort(key=lambda item: item.pattern.display_index)
        return presentations
