from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.adapters.discord import dispatch_channel_command, dispatch_thread_command
from src.adapters.twitch_api import TwitchAPIConfigurationError, TwitchUser
from src.database.connection import ChannelRecord, ChannelRepository, PatternRepository, ThreadRecord, ThreadRepository
from src.events.event_bus import EventBus
from src.events.event_types import DiscordResultStyle
from src.services.channel_command_service import ChannelCommandService, IRCChannelManager
from src.services.thread_lifecycle_service import ThreadLifecycleService


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

    def set_language(self, *, discord_channel_id: int, language: str) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=thread.enabled,
            color=thread.color,
            language=language,
            account_id=thread.account_id,
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
        return [record for record in self.channels_by_thread.values() if record.thread_id == thread_id]


@dataclass
class FakeTwitchAPI:
    users_by_login: dict[str, TwitchUser] = field(default_factory=dict)
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


@dataclass
class FakeIRCManager(IRCChannelManager):
    joined: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)

    async def join_channel(self, channel_login: str) -> None:
        self.joined.append(channel_login)

    async def leave_channel(self, channel_login: str) -> None:
        self.left.append(channel_login)


@dataclass
class FakePatternRepository(PatternRepository):
    references_by_channel: dict[tuple[int, str], int] = field(default_factory=dict)

    def find_exact_pattern(self, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    def add_pattern(self, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    def remove_pattern(self, *, thread_id: int, p_index: int) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    def list_active_patterns_for_thread(self, thread_id: int):  # pragma: no cover - unused here
        raise NotImplementedError

    def set_pattern_priority(self, *, thread_id: int, p_index: int, priority: int):  # pragma: no cover - unused here
        raise NotImplementedError

    def update_pattern(self, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    def get_pattern_by_id(self, *, thread_id: int, p_index: int):  # pragma: no cover - unused here
        raise NotImplementedError

    def list_patterns_for_thread(self, thread_id: int, *, is_regex=None):  # pragma: no cover - unused here
        raise NotImplementedError

    def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        return self.references_by_channel.get((thread_id, twitch_channel_id), 0)


@pytest.mark.asyncio
async def test_channel_command_adds_new_channel_and_joins_irc() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    pattern_repository = FakePatternRepository()
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )
    ThreadLifecycleService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    join_result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="join",
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        twitch_channel_login="Example",
    )

    assert join_result.style == DiscordResultStyle.SUCCESS
    assert join_result.ephemeral is False
    assert result.ephemeral is False
    assert result.style == DiscordResultStyle.SUCCESS
    assert irc_manager.joined == ["example"]
    assert thread_repository.get_by_discord_channel_id(100) is not None


@pytest.mark.asyncio
async def test_channel_command_removes_existing_channel_and_parts_last_irc_subscription() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    pattern_repository = FakePatternRepository()
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="remove",
        twitch_channel_login="example",
    )

    assert result.ephemeral is False
    assert result.style == DiscordResultStyle.SUCCESS
    assert irc_manager.left == ["example"]


@pytest.mark.asyncio
async def test_channel_command_rejects_non_owner_changes() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    pattern_repository = FakePatternRepository()
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=201,
        action="add",
        twitch_channel_login="example",
    )

    assert result.ephemeral is True
    assert result.style == DiscordResultStyle.ERROR


@pytest.mark.asyncio
async def test_channel_command_requires_join_before_adding_channels() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    pattern_repository = FakePatternRepository()
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        twitch_channel_login="example",
    )

    assert result.style == DiscordResultStyle.ERROR
    assert result.ephemeral is True
    assert thread_repository.get_by_discord_channel_id(100) is None
    assert irc_manager.joined == []


@pytest.mark.asyncio
async def test_channel_command_reports_already_added_instead_of_toggling() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    pattern_repository = FakePatternRepository()
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        twitch_channel_login="example",
    )

    assert result.ephemeral is True
    assert result.style == DiscordResultStyle.INFO
    assert channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, "42") is not None
    assert irc_manager.joined == []


@pytest.mark.asyncio
async def test_channel_command_reports_missing_channel_on_remove() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    pattern_repository = FakePatternRepository()
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="remove",
        twitch_channel_login="example",
    )

    assert result.ephemeral is True
    assert result.style == DiscordResultStyle.ERROR
    assert irc_manager.left == []


@pytest.mark.asyncio
async def test_channel_command_rejects_remove_when_scope_still_references_channel() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    pattern_repository = FakePatternRepository(references_by_channel={(thread.thread_id, "42"): 1})
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="remove",
        twitch_channel_login="example",
    )

    assert result.ephemeral is True
    assert result.style == DiscordResultStyle.ERROR
    assert channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, "42") is not None
    assert irc_manager.left == []


@pytest.mark.asyncio
async def test_channel_command_returns_ephemeral_error_for_missing_twitch_credentials() -> None:
    event_bus = EventBus()
    irc_manager = FakeIRCManager()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=FakePatternRepository(),
        twitch_api=FakeTwitchAPI(error=TwitchAPIConfigurationError("Missing Twitch credentials.")),  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        twitch_channel_login="example",
    )

    assert result.ephemeral is True
    assert result.style == DiscordResultStyle.ERROR


@pytest.mark.asyncio
async def test_leave_command_deletes_thread_and_parts_last_irc_channels() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    irc_manager = FakeIRCManager()
    ThreadLifecycleService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=irc_manager,
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="leave",
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert thread_repository.get_by_discord_channel_id(100) is None
    assert irc_manager.left == ["example"]


@pytest.mark.asyncio
async def test_off_command_disables_existing_thread_context() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    ThreadLifecycleService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        irc_manager=FakeIRCManager(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="disable",
    )

    thread = thread_repository.get_by_discord_channel_id(100)
    assert result.style == DiscordResultStyle.SUCCESS
    assert thread is not None
    assert thread.enabled is False


@pytest.mark.asyncio
async def test_on_command_reenables_existing_thread_context() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    thread_repository.set_enabled(discord_channel_id=100, enabled=False)
    ThreadLifecycleService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        irc_manager=FakeIRCManager(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="enable",
    )

    thread = thread_repository.get_by_discord_channel_id(100)
    assert result.style == DiscordResultStyle.SUCCESS
    assert thread is not None
    assert thread.enabled is True


@pytest.mark.asyncio
async def test_channel_color_command_sets_color_for_tracked_channel() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(
        users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")}
    )
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=FakePatternRepository(),
        twitch_api=twitch_api,  # type: ignore[arg-type]
        irc_manager=FakeIRCManager(),
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="color",
        twitch_channel_login="example",
        color="#123456",
        clear_color=False,
    )

    stored = channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, "42")
    assert result.style == DiscordResultStyle.SUCCESS
    assert stored is not None
    assert stored.color == "#123456"


@pytest.mark.asyncio
async def test_context_color_command_sets_thread_color() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    ThreadLifecycleService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        irc_manager=FakeIRCManager(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="color",
        color="#abcdef",
        clear_color=False,
    )

    thread = thread_repository.get_by_discord_channel_id(100)
    assert result.style == DiscordResultStyle.SUCCESS
    assert thread is not None
    assert thread.color == "#abcdef"


@pytest.mark.asyncio
async def test_language_command_updates_thread_language_and_returns_localized_result() -> None:
    event_bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    ThreadLifecycleService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        irc_manager=FakeIRCManager(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="language",
        language="german",
    )

    thread = thread_repository.get_by_discord_channel_id(100)
    assert thread is not None
    assert thread.language == "german"
    assert result.style == DiscordResultStyle.SUCCESS
    assert result.ephemeral is False
