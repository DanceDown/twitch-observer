from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from src.adapters.discord import (
    dispatch_pattern_command,
    dispatch_pattern_edit_command,
    dispatch_show_command,
)
from src.adapters.twitch_api import TwitchUser
from src.database.connection import (
    ChannelRecord,
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import DiscordResultStyle, TwitchChatMessageEvent
from src.services.pattern_service import (
    PatternCommandService,
    PatternTrackingService,
    ShowCommandService,
    TrackingNotificationSender,
)


@dataclass
class InMemoryThreadRepository(ThreadRepository):
    threads_by_channel_id: dict[int, ThreadRecord] = field(default_factory=dict)
    next_thread_id: int = 1

    def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.get(discord_channel_id)

    def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        for thread in self.threads_by_channel_id.values():
            if thread.thread_id == thread_id:
                return thread
        return None

    def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
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

    def delete_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.pop(discord_channel_id, None)

    def set_enabled(self, *, discord_channel_id: int, enabled: bool) -> ThreadRecord | None:
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

    def set_color(self, *, discord_channel_id: int, color: str | None) -> ThreadRecord | None:
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
        key = (thread_id, twitch_channel_id)
        existing = self.channels_by_thread.get(key)
        if existing is None:
            return None
        updated = ChannelRecord(thread_id=existing.thread_id, twitch_channel_id=existing.twitch_channel_id, color=color)
        self.channels_by_thread[key] = updated
        return updated

    def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        return sum(1 for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id)

    def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        return [record.thread_id for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id]

    def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return sorted(
            [record for record in self.channels_by_thread.values() if record.thread_id == thread_id],
            key=lambda record: record.twitch_channel_id,
        )


@dataclass
class InMemoryPatternRepository(PatternRepository):
    patterns: list[PatternRecord] = field(default_factory=list)

    def find_exact_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
    ) -> PatternRecord | None:
        for pattern in self.patterns:
            if (
                pattern.thread_id == thread_id
                and pattern.regex == regex
                and pattern.channel_scope_mode == channel_scope_mode
                and pattern.channel_scope_ids == tuple(sorted(channel_scope_ids))
                and pattern.user_scope_mode == user_scope_mode
                and pattern.user_scope_ids == tuple(sorted(user_scope_ids))
                and pattern.sub_state == sub_state
                and pattern.offline_state == offline_state
                and pattern.is_regex == is_regex
                and pattern.case_sensitive == case_sensitive
            ):
                return pattern
        return None

    def add_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        disabled: bool,
        priority: int,
    ) -> PatternRecord:
        next_index = 1 + max(
            [pattern.p_index for pattern in self.patterns if pattern.thread_id == thread_id],
            default=0,
        )
        record = PatternRecord(
            thread_id=thread_id,
            p_index=next_index,
            regex=regex,
            channel_scope_mode=channel_scope_mode,
            channel_scope_ids=tuple(sorted(channel_scope_ids)),
            user_scope_mode=user_scope_mode,
            user_scope_ids=tuple(sorted(user_scope_ids)),
            sub_state=sub_state,
            offline_state=offline_state,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            color=color,
            disabled=disabled,
            notify=True,
            reply_message=None,
            reply_as_reply=False,
            priority=priority,
        )
        self.patterns.append(record)
        return record

    def remove_pattern(self, *, thread_id: int, p_index: int) -> None:
        self.patterns = [
            pattern
            for pattern in self.patterns
            if not (pattern.thread_id == thread_id and pattern.p_index == p_index)
        ]

    def set_pattern_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.p_index == p_index:
                updated = PatternRecord(
                    thread_id=pattern.thread_id,
                    p_index=pattern.p_index,
                    regex=pattern.regex,
                    channel_scope_mode=pattern.channel_scope_mode,
                    channel_scope_ids=pattern.channel_scope_ids,
                    user_scope_mode=pattern.user_scope_mode,
                    user_scope_ids=pattern.user_scope_ids,
                    sub_state=pattern.sub_state,
                    offline_state=pattern.offline_state,
                    is_regex=pattern.is_regex,
                    case_sensitive=pattern.case_sensitive,
                    color=pattern.color,
                    disabled=disabled,
                    notify=pattern.notify,
                    priority=pattern.priority,
                )
                self.patterns[index] = updated
                return updated
        return None

    def set_pattern_priority(self, *, thread_id: int, p_index: int, priority: int) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.p_index == p_index:
                updated = PatternRecord(
                    thread_id=pattern.thread_id,
                    p_index=pattern.p_index,
                    regex=pattern.regex,
                    channel_scope_mode=pattern.channel_scope_mode,
                    channel_scope_ids=pattern.channel_scope_ids,
                    user_scope_mode=pattern.user_scope_mode,
                    user_scope_ids=pattern.user_scope_ids,
                    sub_state=pattern.sub_state,
                    offline_state=pattern.offline_state,
                    is_regex=pattern.is_regex,
                    case_sensitive=pattern.case_sensitive,
                    color=pattern.color,
                    disabled=pattern.disabled,
                    notify=pattern.notify,
                    priority=priority,
                )
                self.patterns[index] = updated
                return updated
        return None

    def update_pattern(
        self,
        *,
        thread_id: int,
        p_index: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        priority: int,
    ) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.p_index == p_index:
                updated = PatternRecord(
                    thread_id=thread_id,
                    p_index=p_index,
                    regex=regex,
                    channel_scope_mode=channel_scope_mode,
                    channel_scope_ids=tuple(sorted(channel_scope_ids)),
                    user_scope_mode=user_scope_mode,
                    user_scope_ids=tuple(sorted(user_scope_ids)),
                    sub_state=sub_state,
                    offline_state=offline_state,
                    is_regex=is_regex,
                    case_sensitive=case_sensitive,
                    color=color,
                    disabled=pattern.disabled,
                    notify=pattern.notify,
                    priority=priority,
                )
                self.patterns[index] = updated
                return updated
        return None

    def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        rows = [pattern for pattern in self.patterns if pattern.thread_id == thread_id and not pattern.disabled and pattern.notify]
        return sorted(rows, key=lambda pattern: (-pattern.priority, pattern.p_index))

    def get_pattern_by_id(self, *, thread_id: int, p_index: int) -> PatternRecord | None:
        for pattern in self.patterns:
            if pattern.thread_id == thread_id and pattern.p_index == p_index:
                return pattern
        return None

    def list_patterns_for_thread(self, thread_id: int, *, is_regex: bool | None = None) -> list[PatternRecord]:
        rows = [pattern for pattern in self.patterns if pattern.thread_id == thread_id]
        if is_regex is not None:
            rows = [pattern for pattern in rows if pattern.is_regex == is_regex]
        return sorted(rows, key=lambda pattern: (-pattern.priority, pattern.p_index))

    def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        return sum(
            1
            for pattern in self.patterns
            if pattern.thread_id == thread_id and twitch_channel_id in pattern.channel_scope_ids
        )


@dataclass
class InMemoryReplyRepository(ReplyRepository):
    replies_by_pattern: dict[tuple[int, int], ReplyRecord] = field(default_factory=dict)

    def get_by_pattern(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:
        return self.replies_by_pattern.get((thread_id, p_index))

    def add_reply(self, *, thread_id: int, p_index: int, reply_message: str, reply_as_reply: bool) -> ReplyRecord | None:
        reply = ReplyRecord(
            thread_id=thread_id,
            p_index=p_index,
            reply_message=reply_message,
            reply_as_reply=reply_as_reply,
            disabled=False,
        )
        self.replies_by_pattern[(thread_id, p_index)] = reply
        return reply

    def remove_reply(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:
        return self.replies_by_pattern.pop((thread_id, p_index), None)

    def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ReplyRecord]:
        rows = [reply for reply in self.replies_by_pattern.values() if reply.thread_id == thread_id]
        if not include_disabled:
            rows = [reply for reply in rows if not reply.disabled]
        return sorted(rows, key=lambda reply: reply.p_index)

    def disable_replies_for_thread(self, thread_id: int) -> int:
        return 0

    def enable_replies_for_thread(self, thread_id: int) -> int:
        return 0


@dataclass
class FakeTwitchAPI:
    users_by_login: dict[str, TwitchUser] = field(default_factory=dict)
    live_by_user_id: dict[str, bool] = field(default_factory=dict)
    error: Exception | None = None

    async def get_user_by_login(self, login: str) -> TwitchUser:
        if self.error is not None:
            raise self.error
        return self.users_by_login[login.strip().lower()]

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        if self.error is not None:
            raise self.error
        for user in self.users_by_login.values():
            if user.user_id == user_id:
                return user
        raise KeyError(user_id)

    async def is_user_live(self, user_id: str) -> bool:
        return self.live_by_user_id.get(user_id, False)


@dataclass
class FakeNotifier(TrackingNotificationSender):
    sent: list[tuple[int, object]] = field(default_factory=list)

    async def send_tracking_embed(self, discord_channel_id: int, embed) -> None:
        self.sent.append((discord_channel_id, embed))


@pytest.mark.asyncio
async def test_ping_command_adds_pattern_with_selected_channel_scope() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(1, "42")
    pattern_repository = InMemoryPatternRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="only_selected",
        twitch_channel_logins=("example",),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color="#123456",
        disabled=False,
    )

    assert result.title == "Ping Added"
    assert result.style == DiscordResultStyle.SUCCESS
    assert len(pattern_repository.patterns) == 1
    assert pattern_repository.patterns[0].channel_scope_mode == "only_selected"
    assert pattern_repository.patterns[0].channel_scope_ids == ("42",)


@pytest.mark.asyncio
async def test_pattern_command_removes_existing_regex_by_id() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="h.*o",
        pattern_id=None,
        is_regex=True,
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
    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="remove",
        pattern_text=None,
        pattern_id=1,
        is_regex=None,
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

    assert result.title == "Regex Removed"
    assert pattern_repository.patterns == []


@pytest.mark.asyncio
async def test_ping_command_disables_existing_pattern_by_id() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
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
    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="disable",
        pattern_text=None,
        pattern_id=1,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=True,
    )

    assert result.title == "Ping Disabled"
    assert pattern_repository.patterns[0].disabled is True


@pytest.mark.asyncio
async def test_ping_command_enables_disabled_pattern_by_id() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
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
        disabled=True,
    )
    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="enable",
        pattern_text=None,
        pattern_id=1,
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

    assert result.title == "Ping Enabled"
    assert pattern_repository.patterns[0].disabled is False


@pytest.mark.asyncio
async def test_ping_command_requires_join_before_adding_patterns() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
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

    assert result.title == "Not Joined"
    assert pattern_repository.patterns == []


@pytest.mark.asyncio
async def test_pattern_priority_command_updates_existing_pattern_priority() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
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

    result = await dispatch_pattern_edit_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        pattern_id=1,
        pattern_text=None,
        is_regex=None,
        channel_scope_mode=None,
        twitch_channel_logins=None,
        user_scope_mode=None,
        twitch_user_logins=None,
        sub_state=None,
        offline_state=None,
        case_sensitive=None,
        color=None,
        clear_color=False,
        priority=9,
    )

    assert result.title == "Pattern Updated"
    assert pattern_repository.patterns[0].priority == 9


@pytest.mark.asyncio
async def test_pattern_edit_updates_existing_pattern_fields() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(1, "42")
    channel_repository.add_channel(1, "43")
    pattern_repository = InMemoryPatternRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "example": TwitchUser(user_id="42", login="example", display_name="Example"),
            "other": TwitchUser(user_id="43", login="other", display_name="Other"),
            "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
        }
    )
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="only_selected",
        twitch_channel_logins=("example",),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color="#123456",
        disabled=False,
    )

    result = await dispatch_pattern_edit_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        pattern_id=1,
        pattern_text="^hello there$",
        is_regex=True,
        channel_scope_mode="all_except_selected",
        twitch_channel_logins=("other",),
        user_scope_mode="only_selected",
        twitch_user_logins=("alice",),
        sub_state="subs",
        offline_state="online",
        case_sensitive=True,
        color=None,
        clear_color=True,
        priority=9,
    )

    assert result.title == "Pattern Updated"
    updated = pattern_repository.patterns[0]
    assert updated.regex == "^hello there$"
    assert updated.is_regex is True
    assert updated.channel_scope_mode == "all_except_selected"
    assert updated.channel_scope_ids == ("43",)
    assert updated.user_scope_mode == "only_selected"
    assert updated.user_scope_ids == ("7",)
    assert updated.sub_state == "subs"
    assert updated.offline_state == "online"
    assert updated.case_sensitive is True
    assert updated.color is None
    assert updated.priority == 9


@pytest.mark.asyncio
async def test_ping_command_rejects_selected_scope_channels_that_are_not_tracked() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="only_selected",
        twitch_channel_logins=("example",),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.title == "Validation Error"
    assert "not tracked" in result.message
    assert pattern_repository.patterns == []


@pytest.mark.asyncio
async def test_ping_command_supports_all_except_selected_scope() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(1, "42")
    channel_repository.add_channel(1, "43")
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "example": TwitchUser(user_id="42", login="example", display_name="Example"),
            "other": TwitchUser(user_id="43", login="other", display_name="Other"),
        }
    )
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_except_selected",
        twitch_channel_logins=("example",),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.title == "Ping Added"
    assert pattern_repository.patterns[0].channel_scope_mode == "all_except_selected"
    assert pattern_repository.patterns[0].channel_scope_ids == ("42",)


@pytest.mark.asyncio
async def test_ping_command_supports_selected_user_scope() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
        }
    )
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="only_selected",
        twitch_user_logins=("alice",),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.title == "Ping Added"
    assert pattern_repository.patterns[0].user_scope_mode == "only_selected"
    assert pattern_repository.patterns[0].user_scope_ids == ("7",)


@pytest.mark.asyncio
async def test_ping_command_supports_all_except_selected_users() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
        }
    )
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_except_selected",
        twitch_user_logins=("alice",),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.title == "Ping Added"
    assert pattern_repository.patterns[0].user_scope_mode == "all_except_selected"
    assert pattern_repository.patterns[0].user_scope_ids == ("7",)


@pytest.mark.asyncio
async def test_show_command_lists_channels_and_all_pattern_types_together() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="only_selected",
        channel_scope_ids=("42",),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=2,
    )
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="^hello$",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=True,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=0,
    )
    ShowCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=InMemoryReplyRepository(),
    )

    result = await dispatch_show_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        sections=("channels", "pings"),
    )

    assert result.title == "Configuration Overview"
    assert result.ephemeral is True
    assert "twitch_channel_id=`42`" in result.message
    assert "id=`1`" in result.message
    assert "type=`ping`" in result.message
    assert "text=`hello`" in result.message
    assert "scope=`only_selected`" in result.message
    assert "user_scope=`all_users`" in result.message
    assert "type=`regex`" in result.message
    assert "text=`^hello$`" in result.message


@pytest.mark.asyncio
async def test_tracking_service_sends_embed_for_matching_ping_with_pattern_color() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            color="#ffffff",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert len(notifier.sent) == 1
    _, embed = notifier.sent[0]
    assert embed.color.value == 0x123456
    assert embed.title == "Alice"


@pytest.mark.asyncio
async def test_tracking_service_uses_highest_priority_match_and_stops_after_first_match() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#111111",
        disabled=False,
        priority=1,
    )
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello there",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#222222",
        disabled=False,
        priority=9,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello there everyone",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert len(notifier.sent) == 1
    _, embed = notifier.sent[0]
    assert embed.color.value == 0x222222
    assert embed.fields[1].value == "`hello there`"


@pytest.mark.asyncio
async def test_tracking_service_skips_normal_embed_when_pattern_has_enabled_reply() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=True)
    notifier = FakeNotifier()
    service = PatternTrackingService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
        reply_repository=reply_repository,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert notifier.sent == []


@pytest.mark.asyncio
async def test_show_command_lists_patterns_in_priority_order() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    pattern_repository = InMemoryPatternRepository()
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="general",
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
        priority=1,
    )
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="specific",
        channel_scope_mode="only_selected",
        channel_scope_ids=("42",),
        user_scope_mode="only_selected",
        user_scope_ids=("7",),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=8,
    )
    ShowCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=InMemoryReplyRepository(),
    )

    result = await dispatch_show_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        sections=("pings",),
    )

    assert result.title == "Configuration Overview"
    assert result.message.index("text=`specific`") < result.message.index("text=`general`")


@pytest.mark.asyncio
async def test_tracking_service_respects_all_except_selected_user_scope() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_except_selected",
        user_scope_ids=("7",),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            color="#ffffff",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert notifier.sent == []


@pytest.mark.asyncio
async def test_tracking_service_skips_disabled_thread() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=1000)
    thread_repository.set_enabled(discord_channel_id=1000, enabled=False)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert notifier.sent == []
