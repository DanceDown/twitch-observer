from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.gateways.twitch_api import TwitchUser
from src.database.connection import TwitchUserCacheRecord, TwitchUserCacheRepository
from src.events.event_types import TwitchChatMessageEvent
from src.services.twitch_live_query_service import TwitchLiveQueryService
from src.services.twitch_user_directory_service import TwitchUserDirectoryIngestService, TwitchUserDirectoryService


@dataclass
class InMemoryTwitchUserCacheRepository(TwitchUserCacheRepository):
    by_id: dict[str, TwitchUserCacheRecord] = field(default_factory=dict)

    def get_by_user_id(self, twitch_user_id: str) -> TwitchUserCacheRecord | None:
        return self.by_id.get(twitch_user_id)

    def get_by_login(self, twitch_login: str) -> TwitchUserCacheRecord | None:
        normalized = twitch_login.strip().lower()
        for record in self.by_id.values():
            if record.twitch_login == normalized:
                return record
        return None

    def upsert_from_api(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str,
        profile_image_url: str | None,
    ) -> TwitchUserCacheRecord:
        timestamp = datetime.now(UTC).isoformat()
        record = TwitchUserCacheRecord(
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login.strip().lower(),
            display_name=display_name,
            profile_image_url=profile_image_url,
            updated_at=timestamp,
            last_api_refresh_at=timestamp,
        )
        self.by_id[twitch_user_id] = record
        return record

    def observe_from_chat(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str | None,
    ) -> TwitchUserCacheRecord:
        existing = self.by_id.get(twitch_user_id)
        record = TwitchUserCacheRecord(
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login.strip().lower(),
            display_name=(display_name or (existing.display_name if existing is not None else twitch_login)).strip(),
            profile_image_url=None if existing is None else existing.profile_image_url,
            updated_at="chat",
            last_api_refresh_at=None if existing is None else existing.last_api_refresh_at,
        )
        self.by_id[twitch_user_id] = record
        return record


@dataclass
class FakeTwitchAPI:
    users_by_login: dict[str, TwitchUser] = field(default_factory=dict)
    users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    live_user_ids: set[str] = field(default_factory=set)
    login_requests: list[str] = field(default_factory=list)
    id_requests: list[str] = field(default_factory=list)
    live_requests: list[list[str]] = field(default_factory=list)

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_user_by_login(self, login: str) -> TwitchUser:
        normalized = login.strip().lower()
        self.login_requests.append(normalized)
        return self.users_by_login[normalized]

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        normalized = user_id.strip()
        self.id_requests.append(normalized)
        return self.users_by_id[normalized]

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        self.live_requests.append(list(user_ids))
        return {user_id for user_id in user_ids if user_id in self.live_user_ids}

    async def validate_user_access_token(self, access_token: str):
        raise NotImplementedError

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]):
        raise NotImplementedError

    async def poll_device_code_flow(self, *, device_code: str, scopes: tuple[str, ...]):
        raise NotImplementedError

    async def refresh_user_access_token(self, refresh_token: str):
        raise NotImplementedError

    async def send_chat_message(self, **kwargs):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_directory_uses_persistent_cache_before_hitting_helix() -> None:
    repository = InMemoryTwitchUserCacheRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "example": TwitchUser(
                user_id="42",
                login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/avatar.png",
            ),
        },
        users_by_id={
            "42": TwitchUser(
                user_id="42",
                login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/avatar.png",
            ),
        },
    )
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2048,
        api_refresh_interval_seconds=43200,
        channel_api_refresh_interval_seconds=43200,
    )

    first = await directory.get_user_by_login("example")
    second = await directory.get_user_by_login("example")
    by_id = await directory.get_user_by_id("42")

    assert first.display_name == "Example"
    assert second.display_name == "Example"
    assert by_id.login == "example"
    assert twitch_api.login_requests == ["example"]
    assert twitch_api.id_requests == []


@pytest.mark.asyncio
async def test_live_query_service_proxies_live_user_id_lookup_for_live_monitor() -> None:
    twitch_api = FakeTwitchAPI(live_user_ids={"42"})
    live_query = TwitchLiveQueryService(twitch_api)

    result = await live_query.get_live_user_ids(["42", "7"])

    assert result == {"42"}
    assert twitch_api.live_requests == [["42", "7"]]


@pytest.mark.asyncio
async def test_directory_ingests_chat_metadata_without_any_helix_lookup() -> None:
    repository = InMemoryTwitchUserCacheRepository()
    twitch_api = FakeTwitchAPI()
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2048,
        api_refresh_interval_seconds=43200,
        channel_api_refresh_interval_seconds=43200,
    )
    ingest = TwitchUserDirectoryIngestService(directory=directory)

    ingest.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="broadcaster",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello",
        )
    )

    author = directory.get_cached_user_by_login("alice")
    broadcaster = directory.get_cached_user_by_id("42")

    assert author.display_name == "Alice"
    assert broadcaster.login == "broadcaster"
    assert twitch_api.login_requests == []
    assert twitch_api.id_requests == []


@pytest.mark.asyncio
async def test_directory_can_force_a_fresh_login_lookup_when_requested() -> None:
    repository = InMemoryTwitchUserCacheRepository(
        by_id={
            "42": TwitchUserCacheRecord(
                twitch_user_id="42",
                twitch_login="oldname",
                display_name="Old Name",
                profile_image_url=None,
                updated_at="cached",
                last_api_refresh_at=None,
            )
        }
    )
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "newname": TwitchUser(user_id="42", login="newname", display_name="New Name"),
        },
        users_by_id={
            "42": TwitchUser(user_id="42", login="newname", display_name="New Name"),
        },
    )
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2048,
        api_refresh_interval_seconds=43200,
        channel_api_refresh_interval_seconds=43200,
    )

    refreshed = await directory.refresh_user_by_login("newname")
    cached = await directory.get_user_by_id("42")

    assert refreshed.login == "newname"
    assert cached.display_name == "New Name"
    assert twitch_api.login_requests == ["newname"]


@pytest.mark.asyncio
async def test_directory_uses_lru_memory_cache_before_repository() -> None:
    repository = InMemoryTwitchUserCacheRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "alpha": TwitchUser(user_id="1", login="alpha", display_name="Alpha", profile_image_url="a"),
            "beta": TwitchUser(user_id="2", login="beta", display_name="Beta", profile_image_url="b"),
            "gamma": TwitchUser(user_id="3", login="gamma", display_name="Gamma", profile_image_url="c"),
        }
    )
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2,
        api_refresh_interval_seconds=43200,
        channel_api_refresh_interval_seconds=43200,
    )

    await directory.get_user_by_login("alpha")
    await directory.get_user_by_login("beta")
    await directory.get_user_by_login("alpha")
    await directory.get_user_by_login("gamma")

    assert directory.get_cached_user_by_login("alpha") is not None
    assert directory.get_cached_user_by_login("gamma") is not None
    assert directory._get_record_from_memory_by_login("beta") is None


@pytest.mark.asyncio
async def test_directory_cache_only_lookup_does_not_fall_back_to_helix() -> None:
    repository = InMemoryTwitchUserCacheRepository()
    twitch_api = FakeTwitchAPI()
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2048,
        api_refresh_interval_seconds=43200,
        channel_api_refresh_interval_seconds=43200,
    )

    cached = directory.get_cached_user_by_login("unknown")

    assert cached is None
    assert twitch_api.login_requests == []


@pytest.mark.asyncio
async def test_directory_returns_missing_profile_image_from_cached_record_until_explicit_refresh() -> None:
    repository = InMemoryTwitchUserCacheRepository(
        by_id={
            "42": TwitchUserCacheRecord(
                twitch_user_id="42",
                twitch_login="example",
                display_name="Example",
                profile_image_url=None,
                updated_at="cached",
                last_api_refresh_at=None,
            )
        }
    )
    twitch_api = FakeTwitchAPI(
        users_by_id={
            "42": TwitchUser(
                user_id="42",
                login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/avatar.png",
            )
        }
    )
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2048,
        api_refresh_interval_seconds=43200,
        channel_api_refresh_interval_seconds=43200,
    )

    user = await directory.get_user_by_id("42")

    assert user.profile_image_url is None
    assert twitch_api.id_requests == []
    assert repository.get_by_user_id("42").profile_image_url is None


@pytest.mark.asyncio
async def test_directory_returns_stale_user_cache_without_implicit_refresh() -> None:
    repository = InMemoryTwitchUserCacheRepository(
        by_id={
            "42": TwitchUserCacheRecord(
                twitch_user_id="42",
                twitch_login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/old.png",
                updated_at="cached",
                last_api_refresh_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
            )
        }
    )
    twitch_api = FakeTwitchAPI(
        users_by_id={
            "42": TwitchUser(
                user_id="42",
                login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/new.png",
            )
        }
    )
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2048,
        api_refresh_interval_seconds=60,
        channel_api_refresh_interval_seconds=43200,
    )

    user = await directory.get_user_by_id("42")

    assert user.profile_image_url == "https://cdn.example/old.png"
    assert twitch_api.id_requests == []


@pytest.mark.asyncio
async def test_directory_returns_stale_channel_cache_without_implicit_refresh() -> None:
    repository = InMemoryTwitchUserCacheRepository(
        by_id={
            "42": TwitchUserCacheRecord(
                twitch_user_id="42",
                twitch_login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/old.png",
                updated_at="cached",
                last_api_refresh_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
            )
        }
    )
    twitch_api = FakeTwitchAPI(
        users_by_id={
            "42": TwitchUser(
                user_id="42",
                login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/new.png",
            )
        }
    )
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2048,
        api_refresh_interval_seconds=43200,
        channel_api_refresh_interval_seconds=60,
    )

    user = await directory.get_channel_by_id("42")

    assert user.profile_image_url == "https://cdn.example/old.png"
    assert twitch_api.id_requests == []


@pytest.mark.asyncio
async def test_directory_keeps_fresh_channel_cache_without_refresh() -> None:
    repository = InMemoryTwitchUserCacheRepository(
        by_id={
            "42": TwitchUserCacheRecord(
                twitch_user_id="42",
                twitch_login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/current.png",
                updated_at="cached",
                last_api_refresh_at=(datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
            )
        }
    )
    twitch_api = FakeTwitchAPI(
        users_by_id={
            "42": TwitchUser(
                user_id="42",
                login="example",
                display_name="Example",
                profile_image_url="https://cdn.example/new.png",
            )
        }
    )
    directory = TwitchUserDirectoryService(
        twitch_api=twitch_api,
        repository=repository,
        memory_cache_size=2048,
        api_refresh_interval_seconds=43200,
        channel_api_refresh_interval_seconds=60,
    )

    user = await directory.get_channel_by_id("42")

    assert user.profile_image_url == "https://cdn.example/current.png"
    assert twitch_api.id_requests == []
