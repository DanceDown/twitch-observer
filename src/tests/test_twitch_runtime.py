from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.gateways.twitch_api import TwitchChannelNotFoundError, TwitchUser
from src.services.twitch_runtime import safe_get_twitch_user_by_login


@dataclass
class _FakeUserLookup:
    user: TwitchUser
    cached_user: TwitchUser | None = None
    delay_seconds: float = 0
    login_requests: list[str] = field(default_factory=list)
    login_refresh_requests: list[str] = field(default_factory=list)
    refresh_error: Exception | None = None

    async def get_user_by_login(self, login: str) -> TwitchUser:
        normalized = login.strip().lower()
        self.login_requests.append(normalized)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self.user

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        normalized = login.strip().lower()
        self.login_refresh_requests.append(normalized)
        if self.refresh_error is not None:
            raise self.refresh_error
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self.user

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        return self.user

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        return self.user

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        return self.cached_user

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.cached_user

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None:
        return self.cached_user

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.cached_user

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        return (self.user,)


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_login_returns_cached_profile_without_api_call() -> None:
    cached = TwitchUser(user_id="7", login="alice", display_name="Alice", profile_image_url="https://example.test/a.png")
    lookup = _FakeUserLookup(user=cached, cached_user=cached)

    user = await safe_get_twitch_user_by_login(lookup, "Alice", timeout_seconds=0.01)  # type: ignore[arg-type]

    assert user == cached
    assert lookup.login_requests == []
    assert lookup.login_refresh_requests == []


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_login_refreshes_cached_user_without_profile_image() -> None:
    cached = TwitchUser(user_id="7", login="alice", display_name="Alice", profile_image_url=None)
    refreshed = TwitchUser(
        user_id="7",
        login="alice",
        display_name="Alice",
        profile_image_url="https://example.test/a.png",
    )
    lookup = _FakeUserLookup(user=refreshed, cached_user=cached)

    user = await safe_get_twitch_user_by_login(lookup, "Alice", timeout_seconds=0.01)  # type: ignore[arg-type]

    assert user == refreshed
    assert lookup.login_requests == []
    assert lookup.login_refresh_requests == ["alice"]


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_login_keeps_cached_user_when_profile_refresh_fails() -> None:
    cached = TwitchUser(user_id="7", login="alice", display_name="Alice", profile_image_url=None)
    refreshed = TwitchUser(
        user_id="7",
        login="alice",
        display_name="Alice",
        profile_image_url="https://example.test/a.png",
    )
    lookup = _FakeUserLookup(
        user=refreshed,
        cached_user=cached,
        refresh_error=TwitchChannelNotFoundError("not found"),
    )

    user = await safe_get_twitch_user_by_login(lookup, "Alice", timeout_seconds=0.01)  # type: ignore[arg-type]

    assert user == cached
    assert lookup.login_refresh_requests == ["alice"]


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_login_times_out_without_raising() -> None:
    user = TwitchUser(user_id="7", login="alice", display_name="Alice", profile_image_url="https://example.test/a.png")
    lookup = _FakeUserLookup(user=user, delay_seconds=1)

    result = await safe_get_twitch_user_by_login(lookup, "alice", timeout_seconds=0.01)  # type: ignore[arg-type]

    assert result is None
    assert lookup.login_requests == ["alice"]
