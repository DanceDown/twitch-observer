"""Read-only data adapter used by Discord-side configuration forms."""

from __future__ import annotations

from dataclasses import dataclass

from src.services.discord_ui_queries import (
    AdapterEventActionPresentation,
    AdapterEventPresentation,
    DiscordUIQueryBundle,
    PatternPresentation,
    ReplyPresentation,
    TrackedChannelPresentation,
    TrackedUserPresentation,
    WriteReplyCandidatePresentation,
)


@dataclass(slots=True)
class DiscordUIDataProvider:
    """Thin Discord adapter around application-level UI query services."""

    queries: DiscordUIQueryBundle

    async def get_thread_language(self, discord_channel_id: int) -> str | None:
        return await self.queries.channels.get_thread_language(discord_channel_id)

    async def list_tracked_channels(self, discord_channel_id: int) -> list[TrackedChannelPresentation]:
        return await self.queries.channels.list_tracked_channels(discord_channel_id)

    async def list_patterns(self, discord_channel_id: int) -> list[PatternPresentation]:
        return await self.queries.patterns.list_patterns(discord_channel_id)

    async def list_tracked_users(self, discord_channel_id: int) -> list[TrackedUserPresentation]:
        return await self.queries.users.list_tracked_users(discord_channel_id)

    async def list_replies(self, discord_channel_id: int) -> list[ReplyPresentation]:
        return await self.queries.replies.list_replies(discord_channel_id)

    async def list_adapter_events(self, discord_channel_id: int) -> list[AdapterEventPresentation]:
        return await self.queries.events.list_adapter_events(discord_channel_id)

    async def list_adapter_event_actions(self, discord_channel_id: int) -> list[AdapterEventActionPresentation]:
        return await self.queries.events.list_adapter_event_actions(discord_channel_id)

    async def get_pattern(self, discord_channel_id: int, pattern_id: int) -> PatternPresentation | None:
        return await self.queries.patterns.get_pattern(discord_channel_id, pattern_id)

    async def list_recent_write_reply_candidates(
        self,
        *,
        discord_channel_id: int,
        max_age_minutes: int,
        limit: int,
    ) -> list[WriteReplyCandidatePresentation]:
        return await self.queries.write.list_recent_reply_candidates(
            discord_channel_id=discord_channel_id,
            max_age_minutes=max_age_minutes,
            limit=limit,
        )

    async def get_write_reply_candidate(
        self,
        *,
        discord_channel_id: int,
        message_id: str,
    ) -> WriteReplyCandidatePresentation | None:
        return await self.queries.write.get_reply_candidate(
            discord_channel_id=discord_channel_id,
            message_id=message_id,
        )
