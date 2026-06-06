"""Tracked channel query service for Discord UI flows."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import ChannelRepository, ThreadRecord, ThreadRepository
from src.services.twitch_gateways import TwitchDirectoryGateway

from .presentations import TrackedChannelPresentation
from .shared import get_thread_for_channel, resolve_users_by_ids


@dataclass(slots=True)
class TrackedChannelQueryService:
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    twitch_api: TwitchDirectoryGateway

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await get_thread_for_channel(self.thread_repository, discord_channel_id)

    async def get_thread_language(self, discord_channel_id: int) -> str | None:
        thread = await self.get_thread(discord_channel_id)
        return None if thread is None else thread.language

    async def list_tracked_channels(
        self,
        discord_channel_id: int,
        *,
        filter_user_ids: tuple[str, ...] | None = None,
    ) -> list[TrackedChannelPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []

        filter_set = None if filter_user_ids is None else {user_id.strip() for user_id in filter_user_ids if user_id.strip()}
        channels = [
            channel
            for channel in await self.channel_repository.list_channels_for_thread(thread.thread_id)
            if filter_set is None or channel.twitch_channel_id in filter_set
        ]
        resolved_users = await resolve_users_by_ids(
            self.twitch_api,
            tuple(channel.twitch_channel_id for channel in channels),
            channel_lookup=True,
        )
        presentations: list[TrackedChannelPresentation] = []
        for channel in channels:
            twitch_user = resolved_users[channel.twitch_channel_id.strip()]
            presentations.append(
                TrackedChannelPresentation(
                    user_id=twitch_user.user_id,
                    login=twitch_user.login,
                    display_name=twitch_user.display_name,
                    color=channel.color,
                )
            )
        presentations.sort(key=lambda item: item.login)
        return presentations
