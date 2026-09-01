"""Compact display indexes for configured live/offline notification pings."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import AdapterEventActionRepository
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    DISCORD_NOTIFY_ACTION,
    STREAM_OFFLINE_EVENT_KEY,
    STREAM_ONLINE_EVENT_KEY,
    TWITCH_ADAPTER_KEY,
)


@dataclass(slots=True)
class ChannelEventDisplayIndexResolver:
    """Build stable per-thread display IDs for configured live/offline notification actions."""

    adapter_event_action_repository: AdapterEventActionRepository

    async def build_index_map(self, thread_id: int) -> dict[int, int]:
        """Build dense display indexes for notification actions in one thread."""
        rows = [
            (event, action)
            for event, action in await self.adapter_event_action_repository.list_actions_for_thread(
                thread_id,
                include_disabled=True,
            )
            if action.action_type == DISCORD_NOTIFY_ACTION
            and event.adapter_key == TWITCH_ADAPTER_KEY
            and event.subject_type == CHANNEL_SUBJECT_TYPE
            and event.event_key in {STREAM_ONLINE_EVENT_KEY, STREAM_OFFLINE_EVENT_KEY}
        ]
        rows.sort(key=lambda item: item[0].event_id)
        return {event.event_id: display_index for display_index, (event, _) in enumerate(rows, start=1)}

    async def resolve(self, *, thread_id: int, event_id: int) -> int | None:
        """Resolve one event ID to its dense display index."""
        return (await self.build_index_map(thread_id)).get(event_id)
