from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.events.twitch_events import TwitchChannelLiveStateChangedEvent
from src.gateways.twitch_api import TwitchAPIError, TwitchUser
from src.services.twitch_gateways import TwitchLiveMonitorGateway
from src.services.twitch_live_monitor_service import TwitchLiveMonitorService
from src.tests.in_memory_channels import InMemoryChannelRepository as BaseInMemoryChannelRepository


@dataclass
class CollectingLiveStateHandler:
    events: list[TwitchChannelLiveStateChangedEvent] = field(default_factory=list)

    async def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None:
        self.events.append(event)


class InMemoryChannelRepository(BaseInMemoryChannelRepository):
    pass


@dataclass
class FakeTwitchAPI(TwitchLiveMonitorGateway):
    live_by_user_id: dict[str, bool] = field(default_factory=dict)
    users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    requested_batches: list[list[str]] = field(default_factory=list)
    fail_live_lookup: bool = False

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        self.requested_batches.append(list(user_ids))
        if self.fail_live_lookup:
            raise TwitchAPIError("temporary Twitch outage")
        return {user_id for user_id in user_ids if self.live_by_user_id.get(user_id, False)}

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.users_by_id.get(user_id)

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        normalized = login.strip().lower()
        for user in self.users_by_id.values():
            if user.login == normalized:
                return user
        return None

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        return self.users_by_id[user_id]

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        return await self.get_user_by_id(user_id)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        cached = self.get_cached_user_by_login(login)
        if cached is None:
            raise KeyError(login)
        return cached

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        return await self.get_user_by_login(login)

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None:
        return self.get_cached_user_by_login(login)

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.get_cached_user_by_id(user_id)

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        return tuple(user for user_id in user_ids if (user := self.get_cached_user_by_id(user_id)) is not None)


@pytest.mark.asyncio
async def test_live_monitor_initial_sync_persists_state_without_emitting_transition() -> None:
    repository = InMemoryChannelRepository()
    await repository.add_channel(1, "42")
    handler = CollectingLiveStateHandler()
    monitor = TwitchLiveMonitorService(
        channel_repository=repository,
        twitch_api=FakeTwitchAPI(live_by_user_id={"42": True}),
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
        ),
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


@pytest.mark.asyncio
async def test_live_monitor_keeps_previous_state_when_twitch_lookup_fails() -> None:
    repository = InMemoryChannelRepository()
    await repository.add_channel(1, "42")
    await repository.set_live_state_for_twitch_channel(twitch_channel_id="42", is_live=True, changed_at="before")
    handler = CollectingLiveStateHandler()
    monitor = TwitchLiveMonitorService(
        channel_repository=repository,
        twitch_api=FakeTwitchAPI(fail_live_lookup=True),
        poll_interval_seconds=30,
        batch_size=100,
        refresh_on_startup=True,
        on_change=handler,
    )

    await monitor.sync_once(notify_transitions=True)

    stored = await repository.get_by_thread_and_twitch_channel(1, "42")
    assert stored is not None
    assert stored.is_live is True
    assert handler.events == []
