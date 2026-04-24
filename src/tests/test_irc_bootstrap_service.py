from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.adapters.twitch_api import TwitchChannelNotFoundError, TwitchUser
from src.database.connection import ChannelRecord, ChannelRepository
from src.services.irc_bootstrap_service import IRCBootstrapManager, IRCBootstrapService


@dataclass
class InMemoryChannelRepository(ChannelRepository):
    channels_by_thread: dict[tuple[int, str], ChannelRecord] = field(default_factory=dict)

    def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        return self.channels_by_thread.get((thread_id, twitch_channel_id))

    def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread[(thread_id, twitch_channel_id)] = ChannelRecord(
            thread_id=thread_id,
            twitch_channel_id=twitch_channel_id,
            color=None,
        )

    def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread.pop((thread_id, twitch_channel_id), None)

    def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:
        existing = self.channels_by_thread.get((thread_id, twitch_channel_id))
        if existing is None:
            return None
        updated = ChannelRecord(thread_id=thread_id, twitch_channel_id=twitch_channel_id, color=color)
        self.channels_by_thread[(thread_id, twitch_channel_id)] = updated
        return updated

    def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        return sum(1 for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id)

    def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        return [record.thread_id for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id]

    def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return [record for record in self.channels_by_thread.values() if record.thread_id == thread_id]

    def list_all_twitch_channel_ids(self) -> list[str]:
        return sorted({record.twitch_channel_id for record in self.channels_by_thread.values()})


@dataclass
class FakeTwitchAPI:
    users_by_id: dict[str, TwitchUser] = field(default_factory=dict)

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        if user_id not in self.users_by_id:
            raise TwitchChannelNotFoundError(f"Unknown Twitch channel id: {user_id}")
        return self.users_by_id[user_id]


@dataclass
class FakeIRCManager(IRCBootstrapManager):
    joined: list[str] = field(default_factory=list)
    connected: bool = False

    async def wait_until_connected(self) -> None:
        self.connected = True

    async def join_channel(self, channel_login: str) -> None:
        self.joined.append(channel_login)


@pytest.mark.asyncio
async def test_bootstrap_service_joins_all_distinct_persisted_channels() -> None:
    repository = InMemoryChannelRepository()
    repository.add_channel(1, "42")
    repository.add_channel(2, "42")
    repository.add_channel(1, "84")
    twitch_api = FakeTwitchAPI(
        users_by_id={
            "42": TwitchUser(user_id="42", login="example", display_name="Example"),
            "84": TwitchUser(user_id="84", login="second", display_name="Second"),
        }
    )
    irc_manager = FakeIRCManager()
    service = IRCBootstrapService(
        channel_repository=repository,
        twitch_api=twitch_api,
        irc_manager=irc_manager,
        connect_timeout_seconds=15,
    )

    await service.sync_persisted_channels()

    assert irc_manager.connected is True
    assert irc_manager.joined == ["example", "second"]


@pytest.mark.asyncio
async def test_bootstrap_service_skips_channels_that_cannot_be_resolved() -> None:
    repository = InMemoryChannelRepository()
    repository.add_channel(1, "42")
    repository.add_channel(1, "404")
    twitch_api = FakeTwitchAPI(
        users_by_id={"42": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    service = IRCBootstrapService(
        channel_repository=repository,
        twitch_api=twitch_api,
        irc_manager=irc_manager,
        connect_timeout_seconds=15,
    )

    await service.sync_persisted_channels()

    assert irc_manager.joined == ["example"]
