from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.tests.dispatch_helpers import dispatch_pattern_command, dispatch_permission_command, dispatch_show_command
from src.gateways.twitch_api import TwitchUser
from src.database.connection import (
    ChannelRecord,
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    UserPermissionRecord,
    UserPermissionRepository,
)
from types import SimpleNamespace
from src.services.patterns import PatternCommandService, ShowCommandService
from src.services.permission_service import PermissionCommandService


@dataclass
class InMemoryThreadRepository(ThreadRepository):
    threads_by_channel_id: dict[int, ThreadRecord] = field(default_factory=dict)
    next_thread_id: int = 1

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.get(discord_channel_id)

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        for thread in self.threads_by_channel_id.values():
            if thread.thread_id == thread_id:
                return thread
        return None

    async def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
        thread = ThreadRecord(
            thread_id=self.next_thread_id,
            owner_id=owner_id,
            discord_channel_id=discord_channel_id,
            enabled=True,
            color=None,
        )
        self.next_thread_id += 1
        self.threads_by_channel_id[discord_channel_id] = thread
        return thread

    async def delete_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.pop(discord_channel_id, None)

    async def set_enabled(self, *, discord_channel_id: int, enabled: bool) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=enabled,
            color=thread.color,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated

    async def set_color(self, *, discord_channel_id: int, color: str | None) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=thread.enabled,
            color=color,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated


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

    async def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        return sum(1 for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id)

    async def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        return [record.thread_id for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id]

    async def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return [record for record in self.channels_by_thread.values() if record.thread_id == thread_id]


@dataclass
class InMemoryPatternRepository(PatternRepository):
    patterns: list[PatternRecord] = field(default_factory=list)
    next_pattern_id: int = 1

    async def find_exact_pattern(self, **kwargs) -> PatternRecord | None:
        return None

    async def add_pattern(self, **kwargs) -> PatternRecord:
        thread_id = kwargs["thread_id"]
        record = PatternRecord(
            thread_id=thread_id,
            pattern_id=self.next_pattern_id,
            regex=kwargs["regex"],
            channel_scope_mode=kwargs["channel_scope_mode"],
            channel_scope_ids=tuple(sorted(kwargs["channel_scope_ids"])),
            user_scope_mode=kwargs["user_scope_mode"],
            user_scope_ids=tuple(sorted(kwargs["user_scope_ids"])),
            sub_state=kwargs["sub_state"],
            offline_state=kwargs["offline_state"],
            is_regex=kwargs["is_regex"],
            case_sensitive=kwargs["case_sensitive"],
            color=kwargs["color"],
            disabled=kwargs["disabled"],
            notify=True,
            priority=kwargs["priority"],
        )
        self.patterns.append(record)
        self.next_pattern_id += 1
        return record

    async def remove_pattern(self, *, thread_id: int, pattern_id: int) -> None:
        self.patterns = [pattern for pattern in self.patterns if not (pattern.thread_id == thread_id and pattern.pattern_id == pattern_id)]

    async def set_pattern_disabled(self, *, thread_id: int, pattern_id: int, disabled: bool) -> PatternRecord | None:
        return None

    async def set_pattern_priority(self, *, thread_id: int, pattern_id: int, priority: int) -> PatternRecord | None:
        return None

    async def update_pattern(self, **kwargs) -> PatternRecord | None:
        return None

    async def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        return []

    async def get_pattern_by_id(self, *, thread_id: int, pattern_id: int) -> PatternRecord | None:
        for pattern in self.patterns:
            if pattern.thread_id == thread_id and pattern.pattern_id == pattern_id:
                return pattern
        return None

    async def list_patterns_for_thread(self, thread_id: int, *, is_regex: bool | None = None) -> list[PatternRecord]:
        rows = [pattern for pattern in self.patterns if pattern.thread_id == thread_id]
        if is_regex is not None:
            rows = [pattern for pattern in rows if pattern.is_regex == is_regex]
        return rows

    async def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        return 0


@dataclass
class InMemoryReplyRepository(ReplyRepository):
    async def get_by_pattern(self, *, thread_id: int, pattern_id: int):
        return None

    async def add_reply(self, *, thread_id: int, pattern_id: int, reply_message: str, reply_as_reply: bool):
        return None

    async def remove_reply(self, *, thread_id: int, pattern_id: int):
        return None

    async def set_reply_disabled(self, *, thread_id: int, pattern_id: int, disabled: bool):
        return None

    async def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True):
        return []

    async def disable_replies_for_thread(self, thread_id: int) -> int:
        return 0

    async def enable_replies_for_thread(self, thread_id: int) -> int:
        return 0


@dataclass
class InMemoryPermissionRepository(UserPermissionRepository):
    rows: dict[tuple[int, int], UserPermissionRecord] = field(default_factory=dict)

    async def get_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> UserPermissionRecord | None:
        return self.rows.get((discord_user_id, thread_id))

    async def upsert_permissions(self, *, discord_user_id: int, thread_id: int, permissions: int) -> UserPermissionRecord:
        record = UserPermissionRecord(discord_user_id=discord_user_id, thread_id=thread_id, permissions=permissions)
        self.rows[(discord_user_id, thread_id)] = record
        return record

    async def remove_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> bool:
        return self.rows.pop((discord_user_id, thread_id), None) is not None

    async def list_for_thread(self, *, thread_id: int) -> list[UserPermissionRecord]:
        return [record for record in self.rows.values() if record.thread_id == thread_id]


@dataclass
class FakeTwitchAPI:
    users_by_login: dict[str, TwitchUser] = field(default_factory=dict)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        return self.users_by_login[login.strip().lower()]

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        for user in self.users_by_login.values():
            if user.user_id == user_id:
                return user
        raise KeyError(user_id)

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        return await self.get_user_by_id(user_id)

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        return await self.get_user_by_login(login)

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        return None

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return None

    async def is_user_live(self, user_id: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_permission_grant_allows_non_owner_to_add_patterns() -> None:
    bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    pattern_repository = InMemoryPatternRepository()
    permission_repository = InMemoryPermissionRepository()
    twitch_api = FakeTwitchAPI()
    bus.permission = PermissionCommandService(
        thread_repository=thread_repository,
        permission_repository=permission_repository,
    )
    bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        permission_repository=permission_repository,
    )

    grant_result = await dispatch_permission_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="grant",
        target_user_id=201,
        permissions=("manage_patterns",),
    )
    add_result = await dispatch_pattern_command(
        bus,
        discord_channel_id=100,
        requester_id=201,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert grant_result.ephemeral is False
    assert add_result.ephemeral is False
    assert len(pattern_repository.patterns) == 1


@pytest.mark.asyncio
async def test_permission_view_allows_non_owner_to_use_show() -> None:
    bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                pattern_id=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    permission_repository = InMemoryPermissionRepository()
    bus.permission = PermissionCommandService(
        thread_repository=thread_repository,
        permission_repository=permission_repository,
    )
    bus.show = ShowCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=InMemoryReplyRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        permission_repository=permission_repository,
    )

    await dispatch_permission_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="grant",
        target_user_id=201,
        permissions=("view",),
    )
    result = await dispatch_show_command(
        bus,
        discord_channel_id=100,
        requester_id=201,
        sections=("permissions", "pings"),
    )

    assert result.ephemeral is True
    assert result.style.name == "INFO"
    assert result.message
