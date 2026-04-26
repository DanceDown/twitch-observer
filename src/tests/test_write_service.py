from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.adapters.discord import dispatch_permission_command, dispatch_write_command
from src.adapters.twitch_api import TwitchUser, TwitchUserTokenBundle, TwitchValidatedToken
from src.database.connection import (
    ChannelRecord,
    ChannelRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
    UserPermissionRecord,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.services.permission_service import PermissionCommandService
from src.services.write_service import TwitchWriteCommandService


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
            account_id=None,
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
            account_id=thread.account_id,
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
            account_id=thread.account_id,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated

    def set_account_id(self, *, discord_channel_id: int, account_id: int | None) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=thread.enabled,
            color=thread.color,
            account_id=account_id,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated

    def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:
        return [thread for thread in self.threads_by_channel_id.values() if thread.owner_id == owner_id]


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
class InMemoryAccountRepository(TwitchAccountRepository):
    accounts_by_account_id: dict[int, TwitchAccountRecord] = field(default_factory=dict)
    next_account_id: int = 1

    def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:
        return self.accounts_by_account_id.get(account_id)

    def create_account(
        self,
        *,
        discord_user_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord:
        account_id = self.next_account_id
        self.next_account_id += 1
        record = TwitchAccountRecord(
            account_id=account_id,
            discord_user_id=discord_user_id,
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login,
            client_id=client_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            token_type=token_type,
        )
        self.accounts_by_account_id[account_id] = record
        return record

    def update_account(
        self,
        *,
        account_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord | None:
        existing = self.accounts_by_account_id.get(account_id)
        if existing is None:
            return None
        updated = TwitchAccountRecord(
            account_id=account_id,
            discord_user_id=existing.discord_user_id,
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login,
            client_id=client_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            token_type=token_type,
        )
        self.accounts_by_account_id[account_id] = updated
        return updated

    def remove_by_account_id(self, account_id: int) -> bool:
        return self.accounts_by_account_id.pop(account_id, None) is not None

    def get_by_discord_user_id(self, discord_user_id: int) -> TwitchAccountRecord | None:
        matches = [account for account in self.accounts_by_account_id.values() if account.discord_user_id == discord_user_id]
        if not matches:
            return None
        return sorted(matches, key=lambda account: account.account_id)[-1]

    def upsert_account(
        self,
        *,
        discord_user_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord:
        existing = self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return self.create_account(
                discord_user_id=discord_user_id,
                twitch_user_id=twitch_user_id,
                twitch_login=twitch_login,
                client_id=client_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=scope,
                token_type=token_type,
            )
        updated = self.update_account(
            account_id=existing.account_id,
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login,
            client_id=client_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            token_type=token_type,
        )
        assert updated is not None
        return updated

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        existing = self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return self.remove_by_account_id(existing.account_id)


@dataclass
class InMemoryPermissionRepository(UserPermissionRepository):
    rows: dict[tuple[int, int], UserPermissionRecord] = field(default_factory=dict)

    def get_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> UserPermissionRecord | None:
        return self.rows.get((discord_user_id, thread_id))

    def upsert_permissions(self, *, discord_user_id: int, thread_id: int, permissions: int) -> UserPermissionRecord:
        record = UserPermissionRecord(discord_user_id=discord_user_id, thread_id=thread_id, permissions=permissions)
        self.rows[(discord_user_id, thread_id)] = record
        return record

    def remove_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> bool:
        return self.rows.pop((discord_user_id, thread_id), None) is not None

    def list_for_thread(self, *, thread_id: int) -> list[UserPermissionRecord]:
        return [record for record in self.rows.values() if record.thread_id == thread_id]


@dataclass
class FakeTwitchAPI:
    users_by_login: dict[str, TwitchUser] = field(default_factory=dict)
    sent_messages: list[dict[str, str | None]] = field(default_factory=list)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        return self.users_by_login[login.strip().lower()]

    async def send_chat_message(
        self,
        *,
        access_token: str,
        client_id: str,
        sender_id: str,
        broadcaster_id: str,
        message: str,
        reply_parent_message_id: str | None = None,
    ) -> str:
        self.sent_messages.append(
            {
                "access_token": access_token,
                "client_id": client_id,
                "sender_id": sender_id,
                "broadcaster_id": broadcaster_id,
                "message": message,
                "reply_parent_message_id": reply_parent_message_id,
            }
        )
        return "sent-1"

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle:
        return TwitchUserTokenBundle(
            access_token="oauth:refreshed",
            refresh_token=refresh_token,
            expires_in=3600,
            scope=("user:write:chat",),
            token_type="bearer",
        )

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        return TwitchValidatedToken(
            client_id="client-123",
            login="dancedown",
            user_id="77",
            scopes=("user:write:chat",),
            expires_in=3600,
            token_type="bearer",
        )


@pytest.mark.asyncio
async def test_write_send_posts_plain_twitch_message() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    TwitchWriteCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        token_refresh_skew_seconds=30,
        permission_repository=InMemoryPermissionRepository(),
    )

    result = await dispatch_write_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        twitch_channel_login="example",
        message="Hello Twitch",
        reply_parent_message_id=None,
    )

    assert result.ephemeral is False
    assert twitch_api.sent_messages[0]["message"] == "Hello Twitch"
    assert twitch_api.sent_messages[0]["reply_parent_message_id"] is None


@pytest.mark.asyncio
async def test_write_send_can_reply_to_specific_twitch_message() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    TwitchWriteCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        token_refresh_skew_seconds=30,
        permission_repository=InMemoryPermissionRepository(),
    )

    result = await dispatch_write_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        twitch_channel_login="example",
        message="Replying",
        reply_parent_message_id="msg-1",
    )

    assert result.ephemeral is False
    assert twitch_api.sent_messages[0]["reply_parent_message_id"] == "msg-1"


@pytest.mark.asyncio
async def test_write_send_respects_granted_permission_for_non_owner() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    permission_repository = InMemoryPermissionRepository()
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:owner-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    PermissionCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        permission_repository=permission_repository,
    )
    TwitchWriteCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        token_refresh_skew_seconds=30,
        permission_repository=permission_repository,
    )

    await dispatch_permission_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="grant",
        target_user_id=201,
        permissions=("send_twitch_messages",),
    )
    result = await dispatch_write_command(
        bus,
        discord_channel_id=100,
        requester_id=201,
        twitch_channel_login="example",
        message="Helper message",
        reply_parent_message_id=None,
    )

    assert result.ephemeral is False
    assert twitch_api.sent_messages[0]["sender_id"] == "77"


@pytest.mark.asyncio
async def test_write_send_reports_missing_owner_account_even_for_permitted_helper() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(1, "42")
    permission_repository = InMemoryPermissionRepository()
    account_repository = InMemoryAccountRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    PermissionCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        permission_repository=permission_repository,
    )
    TwitchWriteCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        token_refresh_skew_seconds=30,
        permission_repository=permission_repository,
    )

    await dispatch_permission_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="grant",
        target_user_id=201,
        permissions=("send_twitch_messages",),
    )
    result = await dispatch_write_command(
        bus,
        discord_channel_id=100,
        requester_id=201,
        twitch_channel_login="example",
        message="Helper message",
        reply_parent_message_id=None,
    )

    assert result.ephemeral is True
    assert result.style.name == "ERROR"
