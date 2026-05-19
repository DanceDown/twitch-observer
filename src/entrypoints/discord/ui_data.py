"""Read-only data helpers used by Discord-side configuration forms."""

from __future__ import annotations

from dataclasses import dataclass

from src.gateways.twitch_api import TwitchUser
from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    AdapterEventRepository,
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
)
from src.services.twitch_gateways import TwitchDirectoryGateway


@dataclass(slots=True, frozen=True)
class TrackedChannelPresentation:
    """Tracked Twitch channel metadata enriched for Discord UI rendering."""

    user_id: str
    login: str
    display_name: str
    color: str | None


@dataclass(slots=True, frozen=True)
class PatternPresentation:
    """Pattern metadata enriched with resolved Twitch logins for UI display."""

    display_index: int
    pattern: PatternRecord
    channel_logins: tuple[str, ...]
    channel_display_names: tuple[str, ...]
    user_logins: tuple[str, ...]
    user_display_names: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ReplyPresentation:
    """Reply metadata enriched with its attached pattern for UI display."""

    reply: ReplyRecord
    pattern: PatternPresentation


@dataclass(slots=True, frozen=True)
class AdapterEventPresentation:
    """External adapter event metadata enriched for Discord UI rendering."""

    event: AdapterEventRecord
    channel: TrackedChannelPresentation


@dataclass(slots=True, frozen=True)
class AdapterEventActionPresentation:
    """External adapter event action metadata enriched for Discord UI rendering."""

    event: AdapterEventPresentation
    action: AdapterEventActionRecord


@dataclass(slots=True, frozen=True)
class TrackedUserPresentation:
    """Tracked Twitch user metadata enriched for Discord UI rendering."""

    user_id: str
    login: str
    display_name: str


@dataclass(slots=True)
class DiscordUIDataProvider:
    """Expose small read-only query helpers for Discord configuration flows."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    tracked_user_repository: TrackedUserRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    twitch_api: TwitchDirectoryGateway
    adapter_event_repository: AdapterEventRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None

    def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        """Return the stored Discord-context root if it exists."""
        return self.thread_repository.get_by_discord_channel_id(discord_channel_id)

    async def list_tracked_channels(self, discord_channel_id: int) -> list[TrackedChannelPresentation]:
        """Resolve all tracked Twitch channels for one Discord context."""
        thread = self.get_thread(discord_channel_id)
        if thread is None:
            return []

        presentations: list[TrackedChannelPresentation] = []
        for channel in self.channel_repository.list_channels_for_thread(thread.thread_id):
            twitch_user = await self._resolve_channel_by_id(channel.twitch_channel_id)
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

    async def list_patterns(self, discord_channel_id: int) -> list[PatternPresentation]:
        """Resolve all stored patterns with their channel and user login filters."""
        thread = self.get_thread(discord_channel_id)
        if thread is None:
            return []

        presentations: list[PatternPresentation] = []
        for display_index, pattern in enumerate(
            self.pattern_repository.list_patterns_for_thread(thread.thread_id),
            start=1,
        ):
            presentations.append(
                PatternPresentation(
                    display_index=display_index,
                    pattern=pattern,
                    channel_logins=await self._resolve_logins(pattern.channel_scope_ids),
                    channel_display_names=await self._resolve_display_names(pattern.channel_scope_ids),
                    user_logins=await self._resolve_logins(pattern.user_scope_ids),
                    user_display_names=await self._resolve_display_names(pattern.user_scope_ids),
                )
            )
        return presentations

    async def list_tracked_users(self, discord_channel_id: int) -> list[TrackedUserPresentation]:
        """Resolve all tracked Twitch users for one Discord context."""
        thread = self.get_thread(discord_channel_id)
        if thread is None:
            return []

        presentations: list[TrackedUserPresentation] = []
        for tracked_user in self.tracked_user_repository.list_users_for_thread(thread.thread_id):
            twitch_user = await self._resolve_user_by_id(tracked_user.twitch_user_id)
            presentations.append(
                TrackedUserPresentation(
                    user_id=twitch_user.user_id,
                    login=twitch_user.login,
                    display_name=twitch_user.display_name,
                )
            )
        presentations.sort(key=lambda item: item.login)
        return presentations

    async def list_replies(self, discord_channel_id: int) -> list[ReplyPresentation]:
        """Resolve all stored replies together with their attached pattern metadata."""
        thread = self.get_thread(discord_channel_id)
        if thread is None:
            return []

        pattern_map = {item.pattern.pattern_id: item for item in await self.list_patterns(discord_channel_id)}
        presentations: list[ReplyPresentation] = []
        for reply in self.reply_repository.list_replies_for_thread(thread.thread_id, include_disabled=True):
            pattern = pattern_map.get(reply.pattern_id)
            if pattern is None:
                continue
            presentations.append(ReplyPresentation(reply=reply, pattern=pattern))
        presentations.sort(key=lambda item: item.pattern.display_index)
        return presentations

    async def list_adapter_events(self, discord_channel_id: int) -> list[AdapterEventPresentation]:
        """Resolve configured external adapter events for one Discord context."""
        thread = self.get_thread(discord_channel_id)
        if thread is None or self.adapter_event_repository is None:
            return []

        channel_map = {item.user_id: item for item in await self.list_tracked_channels(discord_channel_id)}
        presentations: list[AdapterEventPresentation] = []
        for event in self.adapter_event_repository.list_events_for_thread(thread.thread_id, include_disabled=False):
            if event.adapter_key != "twitch" or event.subject_type != "channel":
                continue
            channel = channel_map.get(event.subject_id)
            if channel is None:
                continue
            presentations.append(AdapterEventPresentation(event=event, channel=channel))
        return presentations

    async def list_adapter_event_actions(self, discord_channel_id: int) -> list[AdapterEventActionPresentation]:
        """Resolve configured external adapter event actions for one Discord context."""
        thread = self.get_thread(discord_channel_id)
        if thread is None or self.adapter_event_repository is None or self.adapter_event_action_repository is None:
            return []

        event_map = {item.event.event_id: item for item in await self.list_adapter_events(discord_channel_id)}
        presentations: list[AdapterEventActionPresentation] = []
        for event_record, action_record in self.adapter_event_action_repository.list_actions_for_thread(
            thread.thread_id,
            include_disabled=True,
        ):
            event = event_map.get(event_record.event_id)
            if event is None:
                continue
            presentations.append(AdapterEventActionPresentation(event=event, action=action_record))
        return presentations

    async def get_pattern(self, discord_channel_id: int, pattern_id: int) -> PatternPresentation | None:
        """Return one pattern presentation by stable ID."""
        patterns = await self.list_patterns(discord_channel_id)
        for pattern in patterns:
            if pattern.pattern.pattern_id == pattern_id:
                return pattern
        return None

    async def _resolve_logins(self, user_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Resolve Twitch user IDs to login names for compact Discord displays."""
        logins: list[str] = []
        for user_id in user_ids:
            twitch_user: TwitchUser = await self._resolve_user_by_id(user_id)
            logins.append(twitch_user.login)
        return tuple(logins)

    async def _resolve_display_names(self, user_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Resolve Twitch user IDs to display names for user-facing Discord text."""
        names: list[str] = []
        for user_id in user_ids:
            twitch_user: TwitchUser = await self._resolve_user_by_id(user_id)
            names.append(twitch_user.display_name)
        return tuple(names)

    async def _resolve_channel_by_id(self, user_id: str) -> TwitchUser:
        return await self.twitch_api.get_channel_by_id(user_id)

    async def _resolve_user_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if normalized_user_id:
            cached = self.twitch_api.get_cached_user_by_id(normalized_user_id)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_id(user_id)
