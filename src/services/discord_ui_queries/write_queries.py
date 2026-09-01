"""Write-related query service for Discord UI flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.database.connection import MessageRepository, ThreadRecord, ThreadRepository

from .presentations import WriteReplyCandidatePresentation
from .shared import get_thread_for_channel


@dataclass(slots=True)
class WriteQueryService:
    """Load Twitch message candidates for Discord write/reply UI flows."""

    thread_repository: ThreadRepository
    message_repository: MessageRepository

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        """Return the thread configured for one Discord channel."""
        return await get_thread_for_channel(self.thread_repository, discord_channel_id)

    async def list_recent_reply_candidates(
        self,
        *,
        discord_channel_id: int,
        max_age_minutes: int,
        limit: int,
    ) -> list[WriteReplyCandidatePresentation]:
        """List recent Twitch messages that can be targeted by manual replies."""
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []
        if max_age_minutes <= 0 or limit <= 0:
            return []

        since = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        rows = await self.message_repository.list_recent_messages_for_thread(
            thread_id=thread.thread_id,
            since=since,
            limit=limit,
        )
        return [
            WriteReplyCandidatePresentation(
                message_id=row.message_id,
                twitch_channel_id=row.twitch_channel_id,
                username=row.username,
                content=row.content,
                timestamp=row.timestamp,
            )
            for row in rows
        ]

    async def get_reply_candidate(
        self,
        *,
        discord_channel_id: int,
        message_id: str,
    ) -> WriteReplyCandidatePresentation | None:
        """Return one recent Twitch message candidate by message ID."""
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return None
        row = await self.message_repository.get_thread_message(
            thread_id=thread.thread_id,
            message_id=message_id,
        )
        if row is None:
            return None
        return WriteReplyCandidatePresentation(
            message_id=row.message_id,
            twitch_channel_id=row.twitch_channel_id,
            username=row.username,
            content=row.content,
            timestamp=row.timestamp,
        )
