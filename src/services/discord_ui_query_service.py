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


async def _load_cached_user_by_id(twitch_api: TwitchDirectoryGateway, user_id: str) -> TwitchUser | None:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        return None
    cached_loader = getattr(twitch_api, "load_cached_user_by_id", None)
    if callable(cached_loader):
        return await resolve_awaitable(cached_loader(normalized_user_id))
    return twitch_api.get_cached_user_by_id(normalized_user_id)


async def _resolve_users_by_ids(
    twitch_api: TwitchDirectoryGateway,
    user_ids: tuple[str, ...],
    *,
    channel_lookup: bool,
) -> dict[str, TwitchUser]:
    resolved: dict[str, TwitchUser] = {}
    normalized_ids = tuple(dict.fromkeys(user_id.strip() for user_id in user_ids if user_id.strip()))
    missing_ids: list[str] = []
    for user_id in normalized_ids:
        cached = await _load_cached_user_by_id(twitch_api, user_id)
        if cached is not None:
            resolved[user_id] = cached
        else:
            missing_ids.append(user_id)
    if missing_ids:
        batch_loader = getattr(twitch_api, "get_users_by_ids", None)
        if callable(batch_loader):
            batch_users = await resolve_awaitable(batch_loader(tuple(missing_ids)))
            for user in batch_users:
                resolved[user.user_id.strip()] = user
        unresolved_ids = [user_id for user_id in missing_ids if user_id not in resolved]
        for user_id in unresolved_ids:
            resolved[user_id] = await twitch_api.get_channel_by_id(user_id) if channel_lookup else await twitch_api.get_user_by_id(user_id)
    return resolved


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
            for channel in await resolve_awaitable(self.channel_repository.list_channels_for_thread(thread.thread_id))
            if filter_set is None or channel.twitch_channel_id in filter_set
        ]
        resolved_users = await _resolve_users_by_ids(
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

        patterns = await resolve_awaitable(self.pattern_repository.list_patterns_for_thread(thread.thread_id))
        channel_users = await _resolve_users_by_ids(
            self.twitch_api,
            tuple(twitch_id for pattern in patterns for twitch_id in pattern.channel_scope_ids),
            channel_lookup=True,
        )
        tracked_users = await _resolve_users_by_ids(
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
        patterns = await self.list_patterns(discord_channel_id)
        for pattern in patterns:
            if pattern.pattern.pattern_id == pattern_id:
                return pattern
        return None


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

        tracked_users = await resolve_awaitable(self.tracked_user_repository.list_users_for_thread(thread.thread_id))
        resolved_users = await _resolve_users_by_ids(
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

        events = await resolve_awaitable(self.adapter_event_repository.list_events_for_thread(thread.thread_id, include_disabled=False))
        relevant_events = [event for event in events if event.adapter_key == "twitch" and event.subject_type == "channel"]
        channel_map = {
            item.user_id: item
            for item in await self.channel_queries.list_tracked_channels(
                discord_channel_id,
                filter_user_ids=tuple(event.subject_id for event in relevant_events),
            )
        }
        presentations: list[AdapterEventPresentation] = []
        for event in relevant_events:
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
        rows = await resolve_awaitable(
            self.message_repository.list_recent_messages_for_thread(
                thread_id=thread.thread_id,
                since=since,
                limit=limit,
            )
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
        thread = await self.get_thread(discord_channel_id)
        if thread is None:
            return None
        row = await resolve_awaitable(
            self.message_repository.get_thread_message(
                thread_id=thread.thread_id,
                message_id=message_id,
            )
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


@dataclass(slots=True)
class DiscordUIQueryBundle:
    channels: TrackedChannelQueryService
    patterns: PatternQueryService
    users: TrackedUserQueryService
    replies: ReplyQueryService
    events: AdapterEventQueryService
    write: WriteQueryService
