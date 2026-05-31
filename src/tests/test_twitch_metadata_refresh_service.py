from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.database.connection import TwitchUserCacheRecord
from src.gateways.twitch_api import TwitchAPIError, TwitchUser
from src.services.twitch_metadata_refresh_service import TwitchMetadataRefreshService


@dataclass
class FakeDirectory:
    cached_records: tuple[TwitchUserCacheRecord, ...] = ()
    users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    requested_batches: list[tuple[str, ...]] = field(default_factory=list)
    upserted_batches: list[tuple[TwitchUser, ...]] = field(default_factory=list)
    failing_batches: set[tuple[str, ...]] = field(default_factory=set)

    async def list_cached_users(self) -> tuple[TwitchUserCacheRecord, ...]:
        return self.cached_records

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        normalized = tuple(user_ids)
        self.requested_batches.append(normalized)
        if normalized in self.failing_batches:
            raise TwitchAPIError("batch failed")
        return tuple(self.users_by_id[user_id] for user_id in normalized if user_id in self.users_by_id)

    def upsert_users_from_api(self, users: tuple[TwitchUser, ...]) -> None:
        self.upserted_batches.append(users)


def _cache_record(user_id: str) -> TwitchUserCacheRecord:
    return TwitchUserCacheRecord(
        twitch_user_id=user_id,
        twitch_login=f"user{user_id}",
        display_name=f"User {user_id}",
        profile_image_url=f"https://example.com/{user_id}.png",
        updated_at="2026-01-01T00:00:00+00:00",
        last_api_refresh_at="2026-01-01T00:00:00+00:00",
    )


def _user(user_id: str) -> TwitchUser:
    return TwitchUser(
        user_id=user_id,
        login=f"user{user_id}",
        display_name=f"User {user_id}",
        profile_image_url=f"https://example.com/{user_id}.png",
    )


@pytest.mark.asyncio
async def test_run_once_refreshes_full_cache_in_100_id_batches() -> None:
    records = tuple(_cache_record(str(index)) for index in range(205))
    directory = FakeDirectory(
        cached_records=records,
        users_by_id={str(index): _user(str(index)) for index in range(205)},
    )
    service = TwitchMetadataRefreshService(
        directory=directory,  # type: ignore[arg-type]
        refresh_interval_seconds=0,
        request_spacing_seconds=0,
        batch_size=100,
    )

    await service.run_once()

    assert [len(batch) for batch in directory.requested_batches] == [100, 100, 5]
    assert [len(batch) for batch in directory.upserted_batches] == [100, 100, 5]
    assert tuple(user_id for batch in directory.requested_batches for user_id in batch) == tuple(str(index) for index in range(205))


def test_spacing_uses_explicit_request_spacing_when_configured() -> None:
    service = TwitchMetadataRefreshService(
        directory=FakeDirectory(),  # type: ignore[arg-type]
        refresh_interval_seconds=3600,
        request_spacing_seconds=15,
    )

    assert service._spacing_seconds_for_batch_count(4) == 15


def test_spacing_distributes_batches_over_refresh_interval_when_not_configured() -> None:
    service = TwitchMetadataRefreshService(
        directory=FakeDirectory(),  # type: ignore[arg-type]
        refresh_interval_seconds=1200,
        request_spacing_seconds=0,
    )

    assert service._spacing_seconds_for_batch_count(4) == 300


@pytest.mark.asyncio
async def test_run_once_skips_empty_cache_without_requests() -> None:
    directory = FakeDirectory()
    service = TwitchMetadataRefreshService(
        directory=directory,  # type: ignore[arg-type]
        refresh_interval_seconds=3600,
        request_spacing_seconds=0,
    )

    await service.run_once()

    assert directory.requested_batches == []
    assert directory.upserted_batches == []


@pytest.mark.asyncio
async def test_run_once_continues_after_batch_error() -> None:
    records = tuple(_cache_record(str(index)) for index in range(4))
    directory = FakeDirectory(
        cached_records=records,
        users_by_id={str(index): _user(str(index)) for index in range(4)},
        failing_batches={("0", "1")},
    )
    service = TwitchMetadataRefreshService(
        directory=directory,  # type: ignore[arg-type]
        refresh_interval_seconds=0,
        request_spacing_seconds=0,
        batch_size=2,
    )

    await service.run_once()

    assert directory.requested_batches == [("0", "1"), ("2", "3")]
    assert [[user.user_id for user in batch] for batch in directory.upserted_batches] == [["2", "3"]]
