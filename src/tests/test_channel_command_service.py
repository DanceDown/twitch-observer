from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.database.connection import PatternCreate, PatternExactQuery, PatternRepository, PatternUpdate, ThreadRecord, ThreadRepository
from src.events.discord_results import DiscordResultStyle
from src.gateways.twitch_api import TwitchAPIConfigurationError, TwitchUser
from src.services.channel_command_service import ChannelCommandService
from src.services.runtime_coordinator import TrackedChannelsChangedNotifier
from src.services.thread_lifecycle_service import ThreadLifecycleService
from src.services.twitch_gateways import TwitchDirectoryGateway, TwitchIRCChannelGateway
from src.tests.dispatch_helpers import dispatch_channel_command, dispatch_thread_command
from src.tests.in_memory_channels import InMemoryChannelRepository as BaseInMemoryChannelRepository


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

    async def set_language(self, *, discord_channel_id: int, language: str) -> ThreadRecord | None:
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


class InMemoryChannelRepository(BaseInMemoryChannelRepository):
    pass


@dataclass
class FakeTwitchAPI(TwitchDirectoryGateway):
    users_by_login: dict[str, TwitchUser] = field(default_factory=dict)
    cached_users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    id_requests: list[str] = field(default_factory=list)
    error: Exception | None = None

    async def get_user_by_login(self, login: str) -> TwitchUser:
        if self.error is not None:
            raise self.error
        return self.users_by_login[login.strip().lower()]

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        return await self.get_user_by_login(login)

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        return await self.get_user_by_login(login)

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        self.id_requests.append(user_id.strip())
        if self.error is not None:
            raise self.error
        for user in self.users_by_login.values():
            if user.user_id == user_id:
                return user
        raise KeyError(user_id)

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        return await self.get_user_by_id(user_id)

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        return await self.get_user_by_id(user_id)

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.cached_users_by_id.get(user_id.strip())

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        normalized = login.strip().lower()
        for user in self.cached_users_by_id.values():
            if user.login == normalized:
                return user
        return None

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None:
        return self.get_cached_user_by_login(login)

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.get_cached_user_by_id(user_id)

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        return tuple(user for user_id in user_ids if (user := self.get_cached_user_by_id(user_id)) is not None)


@dataclass
class FakeIRCGateway(TwitchIRCChannelGateway):
    joined: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)
    left_batches: list[list[str]] = field(default_factory=list)
    ensure_connected_calls: int = 0

    async def ensure_connected(self) -> None:
        self.ensure_connected_calls += 1

    async def join_channel(self, channel_login: str) -> None:
        self.joined.append(channel_login)

    async def join_channels(self, channel_logins: list[str]) -> None:
        self.joined.extend(channel_logins)

    async def leave_channel(self, channel_login: str) -> None:
        self.left.append(channel_login)
        self.left_batches.append([channel_login])

    async def leave_channels(self, channel_logins: list[str]) -> None:
        self.left.extend(channel_logins)
        self.left_batches.append(list(channel_logins))


@dataclass
class FailingIRCGateway(FakeIRCGateway):
    fail_on_join: bool = False
    fail_on_leave: bool = False

    async def join_channel(self, channel_login: str) -> None:
        if self.fail_on_join:
            raise ConnectionError("Connection Lost")
        await super().join_channel(channel_login)

    async def leave_channel(self, channel_login: str) -> None:
        if self.fail_on_leave:
            raise ConnectionError("Connection Lost")
        await super().leave_channel(channel_login)

    async def leave_channels(self, channel_logins: list[str]) -> None:
        if self.fail_on_leave:
            raise ConnectionError("Connection Lost")
        await super().leave_channels(channel_logins)


@dataclass
class FakeTrackedChannelsNotifier(TrackedChannelsChangedNotifier):
    notifications: int = 0

    async def notify_tracked_channels_changed(self) -> None:
        self.notifications += 1


@dataclass
class FakePatternRepository(PatternRepository):
    references_by_channel: dict[tuple[int, str], int] = field(default_factory=dict)

    async def find_exact_pattern(self, query: PatternExactQuery):  # pragma: no cover - unused here
        _ = query
        raise NotImplementedError

    async def add_pattern(self, pattern: PatternCreate):  # pragma: no cover - unused here
        _ = pattern
        raise NotImplementedError

    async def remove_pattern(self, *, thread_id: int, pattern_id: int) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    async def list_active_patterns_for_thread(self, thread_id: int):  # pragma: no cover - unused here
        raise NotImplementedError

    async def set_pattern_priority(self, *, thread_id: int, pattern_id: int, priority: int):  # pragma: no cover - unused here
        raise NotImplementedError

    async def update_pattern(self, pattern: PatternUpdate):  # pragma: no cover - unused here
        _ = pattern
        raise NotImplementedError

    async def get_pattern_by_id(self, *, thread_id: int, pattern_id: int):  # pragma: no cover - unused here
        raise NotImplementedError

    async def list_patterns_for_thread(self, thread_id: int, *, is_regex=None):  # pragma: no cover - unused here
        raise NotImplementedError

    async def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        return self.references_by_channel.get((thread_id, twitch_channel_id), 0)


@pytest.mark.asyncio
async def test_channel_command_adds_new_channel_and_joins_irc() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    pattern_repository = FakePatternRepository()
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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
    assert irc_gateway.joined == ["example"]
    assert await thread_repository.get_by_discord_channel_id(100) is not None


@pytest.mark.asyncio
async def test_channel_command_removes_existing_channel_and_parts_last_irc_subscription() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    pattern_repository = FakePatternRepository()
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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
    assert irc_gateway.left == ["example"]
    assert irc_gateway.ensure_connected_calls == 1


@pytest.mark.asyncio
async def test_channel_command_rejects_non_owner_changes() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    pattern_repository = FakePatternRepository()
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    pattern_repository = FakePatternRepository()
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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
    assert await thread_repository.get_by_discord_channel_id(100) is None
    assert irc_gateway.joined == []


@pytest.mark.asyncio
async def test_channel_command_reports_already_added_instead_of_toggling() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    pattern_repository = FakePatternRepository()
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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
    assert await channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, "42") is not None
    assert irc_gateway.joined == []


@pytest.mark.asyncio
async def test_channel_command_reports_missing_channel_on_remove() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    pattern_repository = FakePatternRepository()
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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
    assert irc_gateway.left == []


@pytest.mark.asyncio
async def test_channel_command_rejects_remove_when_scope_still_references_channel() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    pattern_repository = FakePatternRepository(references_by_channel={(thread.thread_id, "42"): 1})
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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
    assert await channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, "42") is not None
    assert irc_gateway.left == []


@pytest.mark.asyncio
async def test_channel_command_does_not_persist_add_when_irc_join_fails() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FailingIRCGateway(fail_on_join=True)
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=FakePatternRepository(),
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        twitch_channel_login="example",
    )

    assert result.style == DiscordResultStyle.ERROR
    assert await channel_repository.get_by_thread_and_twitch_channel(1, "42") is None


@pytest.mark.asyncio
async def test_channel_command_does_not_remove_last_channel_when_irc_part_fails() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FailingIRCGateway(fail_on_leave=True)
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=FakePatternRepository(),
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_channel_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="remove",
        twitch_channel_login="example",
    )

    assert result.style == DiscordResultStyle.ERROR
    assert await channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, "42") is not None


@pytest.mark.asyncio
async def test_channel_command_returns_ephemeral_error_for_missing_twitch_credentials() -> None:
    event_bus = SimpleNamespace()
    irc_gateway = FakeIRCGateway()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=FakePatternRepository(),
        twitch_api=FakeTwitchAPI(error=TwitchAPIConfigurationError("Missing Twitch credentials.")),
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    irc_gateway = FakeIRCGateway()
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="leave",
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert await thread_repository.get_by_discord_channel_id(100) is None
    assert irc_gateway.left == ["example"]


@pytest.mark.asyncio
async def test_leave_command_parts_last_irc_channels_as_batch() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    await channel_repository.add_channel(thread.thread_id, "84")
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "example": TwitchUser(user_id="42", login="example", display_name="Example"),
            "second": TwitchUser(user_id="84", login="second", display_name="Second"),
        }
    )
    irc_gateway = FakeIRCGateway()
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="leave",
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert irc_gateway.left == ["example", "second"]
    assert irc_gateway.left_batches == [["example", "second"]]


@pytest.mark.asyncio
async def test_leave_command_prefers_cached_channel_metadata() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(
        users_by_login={},
        cached_users_by_id={"42": TwitchUser(user_id="42", login="example", display_name="Example")},
    )
    irc_gateway = FakeIRCGateway()
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        twitch_api=twitch_api,
        irc_gateway=irc_gateway,
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="leave",
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert irc_gateway.left == ["example"]
    assert twitch_api.id_requests == []


@pytest.mark.asyncio
async def test_off_command_disables_existing_thread_context() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),
        irc_gateway=FakeIRCGateway(),
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="disable",
    )

    thread = await thread_repository.get_by_discord_channel_id(100)
    assert result.style == DiscordResultStyle.SUCCESS
    assert thread is not None
    assert thread.enabled is False


@pytest.mark.asyncio
async def test_on_command_reenables_existing_thread_context() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    await thread_repository.set_enabled(discord_channel_id=100, enabled=False)
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),
        irc_gateway=FakeIRCGateway(),
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="enable",
    )

    thread = await thread_repository.get_by_discord_channel_id(100)
    assert result.style == DiscordResultStyle.SUCCESS
    assert thread is not None
    assert thread.enabled is True


@pytest.mark.asyncio
async def test_channel_color_command_sets_color_for_tracked_channel() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    event_bus.channel = ChannelCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=FakePatternRepository(),
        twitch_api=twitch_api,
        irc_gateway=FakeIRCGateway(),
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
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

    stored = await channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, "42")
    assert result.style == DiscordResultStyle.SUCCESS
    assert stored is not None
    assert stored.color == "#123456"


@pytest.mark.asyncio
async def test_context_color_command_sets_thread_color() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),
        irc_gateway=FakeIRCGateway(),
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="color",
        color="#abcdef",
        clear_color=False,
    )

    thread = await thread_repository.get_by_discord_channel_id(100)
    assert result.style == DiscordResultStyle.SUCCESS
    assert thread is not None
    assert thread.color == "#abcdef"


@pytest.mark.asyncio
async def test_context_color_command_reports_same_color_as_info() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    await thread_repository.set_color(discord_channel_id=100, color="#abcdef")
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),
        irc_gateway=FakeIRCGateway(),
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="color",
        color="#abcdef",
        clear_color=False,
    )

    assert result.style == DiscordResultStyle.INFO
    assert result.ephemeral is True
    assert "#abcdef" in result.message


@pytest.mark.asyncio
async def test_language_command_updates_thread_language_and_returns_localized_result() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),
        irc_gateway=FakeIRCGateway(),
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="language",
        language="german",
    )

    thread = await thread_repository.get_by_discord_channel_id(100)
    assert thread is not None
    assert thread.language == "german"
    assert result.style == DiscordResultStyle.SUCCESS
    assert result.ephemeral is False


@pytest.mark.asyncio
async def test_language_command_reports_same_language_as_info() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    await thread_repository.set_language(discord_channel_id=100, language="german")
    event_bus.thread = ThreadLifecycleService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        twitch_api=FakeTwitchAPI(),
        irc_gateway=FakeIRCGateway(),
        tracked_channels_notifier=FakeTrackedChannelsNotifier(),
    )

    result = await dispatch_thread_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="language",
        language="german",
    )

    assert result.style == DiscordResultStyle.INFO
    assert result.ephemeral is True
    assert result.message
