"""Tracked user query service for Discord UI flows."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import ThreadRecord, ThreadRepository, TrackedUserRepository
from src.services.twitch_gateways import TwitchDirectoryGateway

from .presentations import TrackedUserPresentation
from .shared import get_thread_for_channel, resolve_users_by_ids


@dataclass(slots=True)
class TrackedUserQueryService:
    """Load tracked Twitch user data for Discord UI selections."""

    thread_repository: ThreadRepository
    tracked_user_repository: TrackedUserRepository
    twitch_api: TwitchDirectoryGateway

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        """Return the thread configured for one Discord channel."""
        return await get_thread_for_channel(self.thread_repository, discord_channel_id)

    async def list_tracked_users(self, discord_channel_id: int) -> list[TrackedUserPresentation]:
        """List tracked Twitch users with resolved names."""
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []

        tracked_users = await self.tracked_user_repository.list_users_for_thread(thread.thread_id)
        resolved_users = await resolve_users_by_ids(
            self.twitch_api,
            tuple(tracked_user.twitch_user_id for tracked_user in tracked_users),
            channel_lookup=False,
        )
        presentations: list[TrackedUserPresentation] = []
        for tracked_user in tracked_users:
            twitch_user = resolved_users[tracked_user.twitch_user_id.strip()]
            presentations.append(
                TrackedUserPresentation(
                    user_id=twitch_user.user_id,
                    login=twitch_user.login,
                    display_name=twitch_user.display_name,
                )
            )
        presentations.sort(key=lambda item: item.login)
        return presentations
