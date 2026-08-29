"""Adapter event query services for Discord UI flows."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ThreadRecord,
    ThreadRepository,
)
from src.services.channel_event_display_index import ChannelEventDisplayIndexResolver
from src.services.twitch_runtime import DISCORD_NOTIFY_ACTION

from .presentations import AdapterEventActionPresentation, AdapterEventPresentation
from .shared import get_thread_for_channel
from .tracked_channel_queries import TrackedChannelQueryService


@dataclass(slots=True)
class AdapterEventQueryService:
    thread_repository: ThreadRepository
    channel_queries: TrackedChannelQueryService
    adapter_event_repository: AdapterEventRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None

    async def get_thread(self, discord_channel_id: int) -> ThreadRecord | None:
        return await get_thread_for_channel(self.thread_repository, discord_channel_id)

    async def list_adapter_events(self, discord_channel_id: int) -> list[AdapterEventPresentation]:
        thread = await self.get_thread(discord_channel_id)
        if thread is None or self.adapter_event_repository is None:
            return []

        events = await self.adapter_event_repository.list_events_for_thread(thread.thread_id, include_disabled=False)
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
        for event_record, action_record in await self.adapter_event_action_repository.list_actions_for_thread(
            thread.thread_id,
            include_disabled=True,
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
