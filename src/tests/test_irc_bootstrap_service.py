from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.gateways.twitch_api import TwitchChannelNotFoundError, TwitchUser
from src.services.irc_bootstrap_service import IRCBootstrapService
from src.services.twitch_gateways import TwitchIRCConnectionGateway
from src.tests.in_memory_channels import InMemoryChannelRepository as BaseInMemoryChannelRepository


class InMemoryChannelRepository(BaseInMemoryChannelRepository):
    pass


@dataclass
class FakeTwitchAPI:
    users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    cached_users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    id_requests: list[str] = field(default_factory=list)

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.cached_users_by_id.get(user_id.strip())

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        self.id_requests.append(user_id.strip())
        if user_id not in self.users_by_id:
            raise TwitchChannelNotFoundError(f"Unknown Twitch channel id: {user_id}")
        return self.users_by_id[user_id]

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        cached = self.get_cached_user_by_id(user_id)
        if cached is not None:
            return cached
        return await self.get_user_by_id(user_id)


@dataclass
class FakeIRCGateway(TwitchIRCConnectionGateway):
    joined: list[str] = field(default_factory=list)
    connected: bool = False

    async def wait_until_connected(self) -> None:
        self.connected = True

    async def join_channel(self, channel_login: str) -> None:
        self.joined.append(channel_login)


@pytest.mark.asyncio
async def test_bootstrap_service_joins_all_distinct_persisted_channels() -> None:
    repository = InMemoryChannelRepository()
    await repository.add_channel(1, "42")
    await repository.add_channel(2, "42")
    await repository.add_channel(1, "84")
    twitch_api = FakeTwitchAPI(
        users_by_id={
            "42": TwitchUser(user_id="42", login="example", display_name="Example"),
            "84": TwitchUser(user_id="84", login="second", display_name="Second"),
        }
    )
    irc_gateway = FakeIRCGateway()
    service = IRCBootstrapService(
        channel_repository=repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        connect_timeout_seconds=15,
    )

    await service.sync_persisted_channels()

    assert irc_gateway.connected is True
    assert irc_gateway.joined == ["example", "second"]


@pytest.mark.asyncio
async def test_bootstrap_service_skips_channels_that_cannot_be_resolved() -> None:
    repository = InMemoryChannelRepository()
    await repository.add_channel(1, "42")
    await repository.add_channel(1, "404")
    twitch_api = FakeTwitchAPI(users_by_id={"42": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    service = IRCBootstrapService(
        channel_repository=repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        connect_timeout_seconds=15,
    )

    await service.sync_persisted_channels()

    assert irc_gateway.joined == ["example"]


@pytest.mark.asyncio
async def test_bootstrap_service_prefers_cached_channel_metadata() -> None:
    repository = InMemoryChannelRepository()
    await repository.add_channel(1, "42")
    twitch_api = FakeTwitchAPI(
        users_by_id={},
        cached_users_by_id={"42": TwitchUser(user_id="42", login="example", display_name="Example")},
    )
    irc_gateway = FakeIRCGateway()
    service = IRCBootstrapService(
        channel_repository=repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        connect_timeout_seconds=15,
    )

    await service.sync_persisted_channels()

    assert irc_gateway.joined == ["example"]
    assert twitch_api.id_requests == []
