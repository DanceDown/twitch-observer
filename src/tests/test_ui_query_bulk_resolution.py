from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.database.connection import ChannelRepository, PatternRepository, ThreadRepository, TrackedUserRepository
from src.database.records import ChannelRecord, PatternRecord, ThreadRecord, TrackedUserRecord
from src.gateways.twitch_api import TwitchUser
from src.localization import Localizer
from src.services.discord_ui_query_service import PatternQueryService, TrackedChannelQueryService, TrackedUserQueryService
from src.services.patterns.show_renderer import ShowSectionRenderer


@dataclass
class FakeTwitchDirectory:
    users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    cached_users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    batch_requests: list[tuple[str, ...]] = field(default_factory=list)
    user_id_requests: list[str] = field(default_factory=list)
    channel_id_requests: list[str] = field(default_factory=list)

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        normalized = tuple(user_id.strip() for user_id in user_ids)
        self.batch_requests.append(normalized)
        return tuple(self.users_by_id[user_id] for user_id in normalized if user_id in self.users_by_id)

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        normalized = user_id.strip()
        self.user_id_requests.append(normalized)
        return self.users_by_id[normalized]

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        normalized = user_id.strip()
        self.channel_id_requests.append(normalized)
        return self.users_by_id[normalized]

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.cached_users_by_id.get(user_id.strip())

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.get_cached_user_by_id(user_id)


@dataclass
class StaticThreadRepository(ThreadRepository):
    thread: ThreadRecord | None

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        if self.thread is None or self.thread.discord_channel_id != discord_channel_id:
            return None
        return self.thread

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        if self.thread is None or self.thread.thread_id != thread_id:
            return None
        return self.thread


@dataclass
class StaticChannelRepository(ChannelRepository):
    channels: list[ChannelRecord] = field(default_factory=list)

    async def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return [channel for channel in self.channels if channel.thread_id == thread_id]


@dataclass
class StaticPatternRepository(PatternRepository):
    patterns: list[PatternRecord] = field(default_factory=list)

    async def list_patterns_for_thread(self, thread_id: int, *, is_regex: bool | None = None) -> list[PatternRecord]:
        rows = [pattern for pattern in self.patterns if pattern.thread_id == thread_id]
        if is_regex is not None:
            rows = [pattern for pattern in rows if pattern.is_regex == is_regex]
        return rows


@dataclass
class StaticTrackedUserRepository(TrackedUserRepository):
    tracked_users: list[TrackedUserRecord] = field(default_factory=list)

    async def list_users_for_thread(self, thread_id: int) -> list[TrackedUserRecord]:
        return [tracked_user for tracked_user in self.tracked_users if tracked_user.thread_id == thread_id]


def _thread() -> ThreadRecord:
    return ThreadRecord(thread_id=7, owner_id=1, discord_channel_id=42, enabled=True, color=None, language="english")


def _user(user_id: str, login: str) -> TwitchUser:
    return TwitchUser(user_id=user_id, login=login, display_name=login.title(), profile_image_url=None)


@pytest.mark.asyncio
async def test_pattern_query_service_bulk_resolves_scope_users_once() -> None:
    twitch_api = FakeTwitchDirectory(
        users_by_id={
            "11": _user("11", "chanone"),
            "12": _user("12", "chantwo"),
            "21": _user("21", "alice"),
            "22": _user("22", "bob"),
        }
    )
    service = PatternQueryService(
        thread_repository=StaticThreadRepository(_thread()),
        pattern_repository=StaticPatternRepository(
            patterns=[
                PatternRecord(
                    thread_id=7,
                    pattern_id=1,
                    regex="hello",
                    channel_scope_mode="only_selected",
                    channel_scope_ids=("11", "12"),
                    user_scope_mode="only_selected",
                    user_scope_ids=("21", "22"),
                    sub_state="all",
                    offline_state="both",
                    is_regex=False,
                    case_sensitive=False,
                    color=None,
                    disabled=False,
                    priority=0,
                ),
                PatternRecord(
                    thread_id=7,
                    pattern_id=2,
                    regex="world",
                    channel_scope_mode="only_selected",
                    channel_scope_ids=("12",),
                    user_scope_mode="only_selected",
                    user_scope_ids=("22",),
                    sub_state="all",
                    offline_state="both",
                    is_regex=False,
                    case_sensitive=False,
                    color=None,
                    disabled=False,
                    priority=0,
                ),
            ]
        ),
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    patterns = await service.list_patterns(42)

    assert [pattern.display_index for pattern in patterns] == [1, 2]
    assert twitch_api.batch_requests == [("11", "12"), ("21", "22")]
    assert twitch_api.user_id_requests == []
    assert twitch_api.channel_id_requests == []


@pytest.mark.asyncio
async def test_tracked_channel_query_service_bulk_resolves_channels_once() -> None:
    twitch_api = FakeTwitchDirectory(
        users_by_id={
            "11": _user("11", "chanone"),
            "12": _user("12", "chantwo"),
        }
    )
    service = TrackedChannelQueryService(
        thread_repository=StaticThreadRepository(_thread()),
        channel_repository=StaticChannelRepository(
            channels=[
                ChannelRecord(thread_id=7, twitch_channel_id="11", color=None),
                ChannelRecord(thread_id=7, twitch_channel_id="12", color="#123456"),
            ]
        ),
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    channels = await service.list_tracked_channels(42)

    assert [channel.login for channel in channels] == ["chanone", "chantwo"]
    assert twitch_api.batch_requests == [("11", "12")]
    assert twitch_api.channel_id_requests == []


@pytest.mark.asyncio
async def test_tracked_user_query_service_bulk_resolves_users_once() -> None:
    twitch_api = FakeTwitchDirectory(
        users_by_id={
            "21": _user("21", "alice"),
            "22": _user("22", "bob"),
        }
    )
    service = TrackedUserQueryService(
        thread_repository=StaticThreadRepository(_thread()),
        tracked_user_repository=StaticTrackedUserRepository(
            tracked_users=[
                TrackedUserRecord(thread_id=7, twitch_user_id="21"),
                TrackedUserRecord(thread_id=7, twitch_user_id="22"),
            ]
        ),
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    users = await service.list_tracked_users(42)

    assert [user.login for user in users] == ["alice", "bob"]
    assert twitch_api.batch_requests == [("21", "22")]
    assert twitch_api.user_id_requests == []


@pytest.mark.asyncio
async def test_show_renderer_bulk_preloads_tracked_users_section() -> None:
    twitch_api = FakeTwitchDirectory(
        users_by_id={
            "21": _user("21", "alice"),
            "22": _user("22", "bob"),
        }
    )
    renderer = ShowSectionRenderer(
        channel_repository=StaticChannelRepository(),
        pattern_repository=StaticPatternRepository(),
        reply_repository=None,  # type: ignore[arg-type]
        twitch_api=twitch_api,  # type: ignore[arg-type]
        tracked_user_repository=StaticTrackedUserRepository(
            tracked_users=[
                TrackedUserRecord(thread_id=7, twitch_user_id="21"),
                TrackedUserRecord(thread_id=7, twitch_user_id="22"),
            ]
        ),
        localizer=Localizer.from_directory(),
    )

    section = await renderer.render_users_section(_thread())

    assert "alice" in section.lower()
    assert "bob" in section.lower()
    assert twitch_api.batch_requests == [("21", "22")]
    assert twitch_api.user_id_requests == []
