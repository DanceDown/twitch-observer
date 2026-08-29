from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import ChannelRecord, ChannelRepository, TrackedChannelStateRecord


@dataclass
class InMemoryChannelRepository(ChannelRepository):
    channels_by_thread: dict[tuple[int, str], ChannelRecord] = field(default_factory=dict)
    states_by_channel_id: dict[str, TrackedChannelStateRecord] = field(default_factory=dict)

    async def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        record = self.channels_by_thread.get((thread_id, twitch_channel_id))
        if record is None:
            return None
        return self._joined_record(record)

    async def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread[(thread_id, twitch_channel_id)] = ChannelRecord(
            thread_id=thread_id,
            twitch_channel_id=twitch_channel_id,
            color=None,
        )
        self.states_by_channel_id.setdefault(
            twitch_channel_id,
            TrackedChannelStateRecord(
                twitch_channel_id=twitch_channel_id,
                is_live=None,
                last_live_status_at=None,
            ),
        )

    async def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread.pop((thread_id, twitch_channel_id), None)
        if await self.count_threads_by_twitch_channel_id(twitch_channel_id) == 0:
            self.states_by_channel_id.pop(twitch_channel_id, None)

    async def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:
        key = (thread_id, twitch_channel_id)
        existing = self.channels_by_thread.get(key)
        if existing is None:
            return None
        updated = ChannelRecord(
            thread_id=existing.thread_id,
            twitch_channel_id=existing.twitch_channel_id,
            color=color,
        )
        self.channels_by_thread[key] = updated
        return self._joined_record(updated)

    async def set_live_state_for_twitch_channel(
        self,
        *,
        twitch_channel_id: str,
        is_live: bool,
        changed_at: str | None,
    ) -> int:
        if await self.count_threads_by_twitch_channel_id(twitch_channel_id) == 0:
            return 0
        self.states_by_channel_id[twitch_channel_id] = TrackedChannelStateRecord(
            twitch_channel_id=twitch_channel_id,
            is_live=is_live,
            last_live_status_at=changed_at,
        )
        return 1

    async def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        return sum(1 for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id)

    async def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        return [record.thread_id for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id]

    async def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return [
            self._joined_record(record)
            for record in sorted(
                self.channels_by_thread.values(),
                key=lambda row: (row.thread_id, row.twitch_channel_id),
            )
            if record.thread_id == thread_id
        ]

    async def list_all_twitch_channel_ids(self) -> list[str]:
        return sorted({record.twitch_channel_id for record in self.channels_by_thread.values()})

    async def list_distinct_channel_states(self) -> list[TrackedChannelStateRecord]:
        channel_ids = sorted({record.twitch_channel_id for record in self.channels_by_thread.values()})
        return [
            self.states_by_channel_id.get(
                channel_id,
                TrackedChannelStateRecord(
                    twitch_channel_id=channel_id,
                    is_live=None,
                    last_live_status_at=None,
                ),
            )
            for channel_id in channel_ids
        ]

    def _joined_record(self, record: ChannelRecord) -> ChannelRecord:
        state = self.states_by_channel_id.get(record.twitch_channel_id)
        return ChannelRecord(
            thread_id=record.thread_id,
            twitch_channel_id=record.twitch_channel_id,
            color=record.color,
            is_live=None if state is None else state.is_live,
            last_live_status_at=None if state is None else state.last_live_status_at,
        )
