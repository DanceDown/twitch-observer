"""Read-only application query services for Discord UI flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    AdapterEventRepository,
    ChannelRepository,
    MessageRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
)
from src.gateways.twitch_api import TwitchUser
from src.services.channel_event_display_index import ChannelEventDisplayIndexResolver
from src.services.twitch_runtime import DISCORD_NOTIFY_ACTION
from src.services.twitch_gateways import TwitchDirectoryGateway
from src.utils.async_utils import resolve_awaitable


@dataclass(slots=True, frozen=True)
class TrackedChannelPresentation:
    user_id: str
    login: str
    display_name: str
    color: str | None


@dataclass(slots=True, frozen=True)
class PatternPresentation:
    display_index: int
    pattern: PatternRecord
    channel_logins: tuple[str, ...]
    channel_display_names: tuple[str, ...]
    user_logins: tuple[str, ...]
    user_display_names: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ReplyPresentation:
    reply: ReplyRecord
    pattern: PatternPresentation


@dataclass(slots=True, frozen=True)
class AdapterEventPresentation:
    event: AdapterEventRecord
    channel: TrackedChannelPresentation


@dataclass(slots=True, frozen=True)
class AdapterEventActionPresentation:
    event: AdapterEventPresentation
    action: AdapterEventActionRecord
    display_index: int | None = None


@dataclass(slots=True, frozen=True)
class TrackedUserPresentation:
    user_id: str
    login: str
    display_name: str


@dataclass(slots=True, frozen=True)
class WriteReplyCandidatePresentation:
    message_id: str
    twitch_channel_id: str
    username: str
    content: str
    timestamp: datetime


@dataclass(slots=True)
class TrackedChannelQueryService:
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    twitch_api: TwitchDirectoryGateway

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(discord_channel_id))

    async def get_thread_language(self, discord_channel_id: int) -> str | None:
        thread = await self.get_thread(discord_channel_id)
        return None if thread is None else thread.language

    async def list_tracked_channels(self, discord_channel_id: int) -> list[TrackedChannelPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []

        presentations: list[TrackedChannelPresentation] = []
        for channel in await resolve_awaitable(self.channel_repository.list_channels_for_thread(thread.thread_id)):
            twitch_user = await self.twitch_api.get_channel_by_id(channel.twitch_channel_id)
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


@dataclass(slots=True)
class PatternQueryService:
    thread_repository: ThreadRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchDirectoryGateway

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(discord_channel_id))

    async def list_patterns(self, discord_channel_id: int) -> list[PatternPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []

        presentations: list[PatternPresentation] = []
        for display_index, pattern in enumerate(
            await resolve_awaitable(self.pattern_repository.list_patterns_for_thread(thread.thread_id)), start=1
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

    async def get_pattern(self, discord_channel_id: int, pattern_id: int) -> PatternPresentation | None:
        patterns = await self.list_patterns(discord_channel_id)
        for pattern in patterns:
            if pattern.pattern.pattern_id == pattern_id:
                return pattern
        return None

    async def _resolve_logins(self, user_ids: tuple[str, ...]) -> tuple[str, ...]:
        logins: list[str] = []
        for user_id in user_ids:
            user = await self._resolve_user_by_id(user_id)
            logins.append(user.login)
        return tuple(logins)

    async def _resolve_display_names(self, user_ids: tuple[str, ...]) -> tuple[str, ...]:
        names: list[str] = []
        for user_id in user_ids:
            user = await self._resolve_user_by_id(user_id)
            names.append(user.display_name)
        return tuple(names)

    async def _resolve_user_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if normalized_user_id:
            cached = self.twitch_api.get_cached_user_by_id(normalized_user_id)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_id(user_id)


@dataclass(slots=True)
class TrackedUserQueryService:
    thread_repository: ThreadRepository
    tracked_user_repository: TrackedUserRepository
    twitch_api: TwitchDirectoryGateway

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(discord_channel_id))

    async def list_tracked_users(self, discord_channel_id: int) -> list[TrackedUserPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []

        presentations: list[TrackedUserPresentation] = []
        for tracked_user in await resolve_awaitable(self.tracked_user_repository.list_users_for_thread(thread.thread_id)):
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

    async def _resolve_user_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if normalized_user_id:
            cached = self.twitch_api.get_cached_user_by_id(normalized_user_id)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_id(user_id)


@dataclass(slots=True)
class ReplyQueryService:
    thread_repository: ThreadRepository
    reply_repository: ReplyRepository
    pattern_queries: PatternQueryService

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(discord_channel_id))

    async def list_replies(self, discord_channel_id: int) -> list[ReplyPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []

        pattern_map = {item.pattern.pattern_id: item for item in await self.pattern_queries.list_patterns(discord_channel_id)}
        presentations: list[ReplyPresentation] = []
        for reply in await resolve_awaitable(self.reply_repository.list_replies_for_thread(thread.thread_id, include_disabled=True)):
            pattern = pattern_map.get(reply.pattern_id)
            if pattern is None:
                continue
            presentations.append(ReplyPresentation(reply=reply, pattern=pattern))
        presentations.sort(key=lambda item: item.pattern.display_index)
        return presentations


@dataclass(slots=True)
class AdapterEventQueryService:
    thread_repository: ThreadRepository
    channel_queries: TrackedChannelQueryService
    adapter_event_repository: AdapterEventRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(discord_channel_id))

    async def list_adapter_events(self, discord_channel_id: int) -> list[AdapterEventPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None or self.adapter_event_repository is None:
            return []

        channel_map = {item.user_id: item for item in await self.channel_queries.list_tracked_channels(discord_channel_id)}
        presentations: list[AdapterEventPresentation] = []
        for event in await resolve_awaitable(
            self.adapter_event_repository.list_events_for_thread(thread.thread_id, include_disabled=False)
        ):
            if event.adapter_key != "twitch" or event.subject_type != "channel":
                continue
            channel = channel_map.get(event.subject_id)
            if channel is None:
                continue
            presentations.append(AdapterEventPresentation(event=event, channel=channel))
        return presentations

    async def list_adapter_event_actions(self, discord_channel_id: int) -> list[AdapterEventActionPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None or self.adapter_event_repository is None or self.adapter_event_action_repository is None:
            return []

        event_map = {item.event.event_id: item for item in await self.list_adapter_events(discord_channel_id)}
        display_index_map = await ChannelEventDisplayIndexResolver(self.adapter_event_action_repository).build_index_map(thread.thread_id)
        presentations: list[AdapterEventActionPresentation] = []
        for event_record, action_record in await resolve_awaitable(
            self.adapter_event_action_repository.list_actions_for_thread(
                thread.thread_id,
                include_disabled=True,
            )
        ):
            event = event_map.get(event_record.event_id)
            if event is None:
                continue
            presentations.append(
                AdapterEventActionPresentation(
                    event=event,
                    action=action_record,
                    display_index=(
                        display_index_map.get(event_record.event_id) if action_record.action_type == DISCORD_NOTIFY_ACTION else None
                    ),
                )
            )
        presentations.sort(
            key=lambda item: (
                item.display_index is None,
                item.display_index or 0,
                item.event.event.event_id,
                item.action.action_type,
            )
        )
        return presentations


@dataclass(slots=True)
class WriteQueryService:
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    message_repository: MessageRepository

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(discord_channel_id))

    async def list_recent_reply_candidates(
        self,
        *,
        discord_channel_id: int,
        max_age_minutes: int,
        limit: int,
    ) -> list[WriteReplyCandidatePresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return []
        if max_age_minutes <= 0 or limit <= 0:
            return []

        since = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        candidates: list[WriteReplyCandidatePresentation] = []
        for channel in await resolve_awaitable(self.channel_repository.list_channels_for_thread(thread.thread_id)):
            rows = await resolve_awaitable(
                self.message_repository.list_recent_messages_for_channel(
                    twitch_channel_id=channel.twitch_channel_id,
                    since=since,
                    limit=limit,
                )
            )
            for row in rows:
                candidates.append(
                    WriteReplyCandidatePresentation(
                        message_id=row.message_id,
                        twitch_channel_id=row.twitch_channel_id,
                        username=row.username,
                        content=row.content,
                        timestamp=row.timestamp,
                    )
                )
        candidates.sort(key=lambda item: item.timestamp, reverse=True)
        return candidates[:limit]


@dataclass(slots=True)
class DiscordUIQueryBundle:
    channels: TrackedChannelQueryService
    patterns: PatternQueryService
    users: TrackedUserQueryService
    replies: ReplyQueryService
    events: AdapterEventQueryService
    write: WriteQueryService
