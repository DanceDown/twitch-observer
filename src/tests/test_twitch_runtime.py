from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.gateways.twitch_api import TwitchChannelNotFoundError, TwitchUser
from src.services.twitch_gateways import TwitchUserLookup
from src.services.twitch_runtime import safe_get_twitch_user_by_id, safe_get_twitch_user_by_login


@dataclass
class _FakeUserLookup(TwitchUserLookup):
    user: TwitchUser
    cached_user: TwitchUser | None = None
    delay_seconds: float = 0
    login_requests: list[str] = field(default_factory=list)
    login_refresh_requests: list[str] = field(default_factory=list)
    login_chat_color_requests: list[str] = field(default_factory=list)
    id_chat_color_requests: list[str] = field(default_factory=list)
    login_chat_color_refresh_requests: list[str] = field(default_factory=list)
    id_chat_color_refresh_requests: list[str] = field(default_factory=list)
    refresh_error: Exception | None = None

    async def get_user_by_login(self, login: str) -> TwitchUser:
        normalized = login.strip().lower()
        self.login_requests.append(normalized)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self.user

    async def get_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        normalized = login.strip().lower()
        self.login_chat_color_requests.append(normalized)
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

    async def refresh_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        normalized = login.strip().lower()
        self.login_chat_color_refresh_requests.append(normalized)
        if self.refresh_error is not None:
            raise self.refresh_error
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self.user

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        _ = user_id
        return self.user

    async def get_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        normalized = user_id.strip()
        self.id_chat_color_requests.append(normalized)
        return self.user

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        _ = user_id
        return self.user

    async def refresh_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        normalized = user_id.strip()
        self.id_chat_color_refresh_requests.append(normalized)
        return self.user

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        _ = login
        return self.cached_user

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        _ = user_id
        return self.cached_user

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None:
        _ = login
        return self.cached_user

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        _ = user_id
        return self.cached_user

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        _ = user_ids
        return (self.user,)


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_login_returns_cached_profile_without_api_call() -> None:
    cached = TwitchUser(user_id="7", login="alice", display_name="Alice", profile_image_url="https://example.test/a.png")
    lookup = _FakeUserLookup(user=cached, cached_user=cached)

    user = await safe_get_twitch_user_by_login(lookup, "Alice", timeout_seconds=0.01)

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

    user = await safe_get_twitch_user_by_login(lookup, "Alice", timeout_seconds=0.01)

    assert user == refreshed
    assert lookup.login_requests == []
    assert lookup.login_refresh_requests == ["alice"]
    assert lookup.login_chat_color_refresh_requests == []


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_id_refreshes_cached_user_without_required_chat_color() -> None:
    cached = TwitchUser(
        user_id="7",
        login="alice",
        display_name="Alice",
        profile_image_url="https://example.test/old.png",
        chat_color=None,
    )
    refreshed = TwitchUser(
        user_id="7",
        login="alice",
        display_name="Alice",
        profile_image_url="https://example.test/a.png",
        chat_color="#AA00BB",
    )
    lookup = _FakeUserLookup(user=refreshed, cached_user=cached)

    user = await safe_get_twitch_user_by_id(lookup, "7", timeout_seconds=0.01, require_chat_color=True)

    assert user == refreshed
    assert lookup.id_chat_color_refresh_requests == ["7"]


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_id_uses_chat_color_lookup_on_cache_miss_when_required() -> None:
    user_with_color = TwitchUser(
        user_id="7",
        login="alice",
        display_name="Alice",
        profile_image_url="https://example.test/a.png",
        chat_color="#AA00BB",
    )
    lookup = _FakeUserLookup(user=user_with_color)

    user = await safe_get_twitch_user_by_id(lookup, "7", timeout_seconds=0.01, require_chat_color=True)

    assert user == user_with_color
    assert lookup.id_chat_color_requests == ["7"]


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_login_refreshes_cached_user_without_required_chat_color() -> None:
    cached = TwitchUser(
        user_id="7",
        login="alice",
        display_name="Alice",
        profile_image_url="https://example.test/old.png",
        chat_color=None,
    )
    refreshed = TwitchUser(
        user_id="7",
        login="alice",
        display_name="Alice",
        profile_image_url="https://example.test/a.png",
        chat_color="#AA00BB",
    )
    lookup = _FakeUserLookup(user=refreshed, cached_user=cached)

    user = await safe_get_twitch_user_by_login(lookup, "Alice", timeout_seconds=0.01, require_chat_color=True)

    assert user == refreshed
    assert lookup.login_requests == []
    assert lookup.login_refresh_requests == []
    assert lookup.login_chat_color_refresh_requests == ["alice"]


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_login_treats_empty_required_chat_color_as_known() -> None:
    cached = TwitchUser(
        user_id="7",
        login="alice",
        display_name="Alice",
        profile_image_url="https://example.test/a.png",
        chat_color="",
    )
    lookup = _FakeUserLookup(user=cached, cached_user=cached)

    user = await safe_get_twitch_user_by_login(lookup, "Alice", timeout_seconds=0.01, require_chat_color=True)

    assert user == cached
    assert lookup.login_requests == []
    assert lookup.login_refresh_requests == []


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

    user = await safe_get_twitch_user_by_login(lookup, "Alice", timeout_seconds=0.01)

    assert user == cached
    assert lookup.login_refresh_requests == ["alice"]


@pytest.mark.asyncio
async def test_safe_get_twitch_user_by_login_times_out_without_raising() -> None:
    user = TwitchUser(user_id="7", login="alice", display_name="Alice", profile_image_url="https://example.test/a.png")
    lookup = _FakeUserLookup(user=user, delay_seconds=1)

    result = await safe_get_twitch_user_by_login(lookup, "alice", timeout_seconds=0.01)

    assert result is None
    assert lookup.login_requests == ["alice"]
