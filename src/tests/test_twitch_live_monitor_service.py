from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.gateways.twitch_api import TwitchUser
from src.database.connection import ChannelRecord, ChannelRepository, TrackedChannelStateRecord
from src.events.twitch_events import TwitchChannelLiveStateChangedEvent
from src.services.twitch_live_monitor_service import TwitchLiveMonitorService


@dataclass
class CollectingLiveStateHandler:
    events: list[TwitchChannelLiveStateChangedEvent] = field(default_factory=list)

    async def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None:
        self.events.append(event)


@dataclass
class InMemoryChannelRepository(ChannelRepository):
    channels_by_thread: dict[tuple[int, str], ChannelRecord] = field(default_factory=dict)

    async def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        return self.channels_by_thread.get((thread_id, twitch_channel_id))

    async def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread[(thread_id, twitch_channel_id)] = ChannelRecord(
            thread_id=thread_id,
            twitch_channel_id=twitch_channel_id,
            color=None,
        )

    async def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread.pop((thread_id, twitch_channel_id), None)

    async def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:
        existing = self.channels_by_thread.get((thread_id, twitch_channel_id))
        if existing is None:
            return None
        updated = ChannelRecord(
            thread_id=existing.thread_id,
            twitch_channel_id=existing.twitch_channel_id,
            color=color,
            is_live=existing.is_live,
            last_live_status_at=existing.last_live_status_at,
        )
        self.channels_by_thread[(thread_id, twitch_channel_id)] = updated
        return updated

    async def set_live_state_for_twitch_channel(self, *, twitch_channel_id: str, is_live: bool, changed_at: str | None) -> int:
        updated_rows = 0
        for key, existing in list(self.channels_by_thread.items()):
            if existing.twitch_channel_id != twitch_channel_id:
                continue
            self.channels_by_thread[key] = ChannelRecord(
                thread_id=existing.thread_id,
                twitch_channel_id=existing.twitch_channel_id,
                color=existing.color,
                is_live=is_live,
                last_live_status_at=changed_at,
            )
            updated_rows += 1
        return updated_rows

    async def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        return sum(1 for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id)

    async def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        return [record.thread_id for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id]

    async def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return [record for record in self.channels_by_thread.values() if record.thread_id == thread_id]

    async def list_all_twitch_channel_ids(self) -> list[str]:
        return sorted({record.twitch_channel_id for record in self.channels_by_thread.values()})

    async def list_distinct_channel_states(self) -> list[TrackedChannelStateRecord]:
        rows: dict[str, TrackedChannelStateRecord] = {}
        for record in self.channels_by_thread.values():
            rows[record.twitch_channel_id] = TrackedChannelStateRecord(
                twitch_channel_id=record.twitch_channel_id,
                is_live=record.is_live,
                last_live_status_at=record.last_live_status_at,
            )
        return [rows[channel_id] for channel_id in sorted(rows)]


@dataclass
class FakeTwitchAPI:
    live_by_user_id: dict[str, bool] = field(default_factory=dict)
    users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    requested_batches: list[list[str]] = field(default_factory=list)

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        self.requested_batches.append(list(user_ids))
        return {user_id for user_id in user_ids if self.live_by_user_id.get(user_id, False)}

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.users_by_id.get(user_id)

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        return self.users_by_id[user_id]


@pytest.mark.asyncio
async def test_live_monitor_initial_sync_persists_state_without_emitting_transition() -> None:
    repository = InMemoryChannelRepository()
    await repository.add_channel(1, "42")
    handler = CollectingLiveStateHandler()
    monitor = TwitchLiveMonitorService(
        channel_repository=repository,
        twitch_api=FakeTwitchAPI(live_by_user_id={"42": True}),  # type: ignore[arg-type]
        poll_interval_seconds=30,
        batch_size=100,
        refresh_on_startup=True,
        on_change=handler,
    )

    await monitor.sync_once(notify_transitions=False)

    stored = await repository.get_by_thread_and_twitch_channel(1, "42")
    assert stored is not None
    assert stored.is_live is True
    assert handler.events == []


@pytest.mark.asyncio
async def test_live_monitor_emits_transition_event_after_known_state_changes() -> None:
    repository = InMemoryChannelRepository()
    await repository.add_channel(1, "42")
    await repository.set_live_state_for_twitch_channel(twitch_channel_id="42", is_live=False, changed_at="before")
    handler = CollectingLiveStateHandler()
    monitor = TwitchLiveMonitorService(
        channel_repository=repository,
        twitch_api=FakeTwitchAPI(
            live_by_user_id={"42": True},
            users_by_id={"42": TwitchUser(user_id="42", login="example", display_name="Example")},
        ),  # type: ignore[arg-type]
        poll_interval_seconds=30,
        batch_size=100,
        refresh_on_startup=True,
        on_change=handler,
    )

    await monitor.sync_once(notify_transitions=True)

    assert len(handler.events) == 1
    assert handler.events[0].twitch_channel_id == "42"
    assert handler.events[0].twitch_channel_login == "example"
    assert handler.events[0].is_live is True
