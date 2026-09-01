"""Pattern query service for Discord UI flows."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import PatternRepository, ThreadRecord, ThreadRepository
from src.services.twitch_gateways import TwitchDirectoryGateway

from .presentations import PatternPresentation
from .shared import get_thread_for_channel, resolve_users_by_ids


@dataclass(slots=True)
class PatternQueryService:
    """Load ping pattern data for Discord UI selections."""

    thread_repository: ThreadRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchDirectoryGateway

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        """Return the thread configured for one Discord channel."""
        return await get_thread_for_channel(self.thread_repository, discord_channel_id)

    async def list_patterns(self, discord_channel_id: int) -> list[PatternPresentation]:
        """List patterns with display indexes and resolved Twitch names."""
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []

        patterns = await self.pattern_repository.list_patterns_for_thread(thread.thread_id)
        channel_users = await resolve_users_by_ids(
            self.twitch_api,
            tuple(twitch_id for pattern in patterns for twitch_id in pattern.channel_scope_ids),
            channel_lookup=True,
        )
        tracked_users = await resolve_users_by_ids(
            self.twitch_api,
            tuple(twitch_id for pattern in patterns for twitch_id in pattern.user_scope_ids),
            channel_lookup=False,
        )
        presentations: list[PatternPresentation] = []
        for display_index, pattern in enumerate(patterns, start=1):
            presentations.append(
                PatternPresentation(
                    display_index=display_index,
                    pattern=pattern,
                    channel_logins=tuple(channel_users[user_id.strip()].login for user_id in pattern.channel_scope_ids if user_id.strip()),
                    channel_display_names=tuple(
                        channel_users[user_id.strip()].display_name for user_id in pattern.channel_scope_ids if user_id.strip()
                    ),
                    user_logins=tuple(tracked_users[user_id.strip()].login for user_id in pattern.user_scope_ids if user_id.strip()),
                    user_display_names=tuple(
                        tracked_users[user_id.strip()].display_name for user_id in pattern.user_scope_ids if user_id.strip()
                    ),
                )
            )
        return presentations

    async def get_pattern(self, discord_channel_id: int, pattern_id: int) -> PatternPresentation | None:
        """Return one pattern presentation by database pattern ID."""
        patterns = await self.list_patterns(discord_channel_id)
        for pattern in patterns:
            if pattern.pattern.pattern_id == pattern_id:
                return pattern
        return None
