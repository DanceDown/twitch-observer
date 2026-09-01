from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.database.connection import (
    ThreadRecord,
    ThreadRepository,
    TwitchAccountCreate,
    TwitchAccountRecord,
    TwitchAccountRepository,
    TwitchAccountTokenData,
    TwitchAccountUpdate,
    UserPermissionRecord,
    UserPermissionRepository,
)
from src.events.twitch_events import TwitchChatSendRequest
from src.gateways.twitch_api import TwitchDeviceCodeStart, TwitchDevicePollResult, TwitchUser, TwitchUserTokenBundle, TwitchValidatedToken
from src.services.permission_service import PermissionCommandService
from src.services.write_service import TwitchWriteCommandService, TwitchWriteGateway
from src.tests.dispatch_helpers import dispatch_permission_command, dispatch_write_command
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
            account_id=None,
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
            account_id=thread.account_id,
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
            account_id=thread.account_id,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated

    async def set_account_id(self, *, discord_channel_id: int, account_id: int | None) -> ThreadRecord | None:
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

    async def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:
        return [thread for thread in self.threads_by_channel_id.values() if thread.owner_id == owner_id]


class InMemoryChannelRepository(BaseInMemoryChannelRepository):
    pass


@dataclass
class InMemoryAccountRepository(TwitchAccountRepository):
    accounts_by_account_id: dict[int, TwitchAccountRecord] = field(default_factory=dict)
    next_account_id: int = 1

    async def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:
        return self.accounts_by_account_id.get(account_id)

    async def create_account(self, account: TwitchAccountCreate) -> TwitchAccountRecord:
        account_id = self.next_account_id
        self.next_account_id += 1
        token = account.token
        record = TwitchAccountRecord(
            account_id=account_id,
            discord_user_id=account.discord_user_id,
            twitch_user_id=token.twitch_user_id,
            twitch_login=token.twitch_login,
            client_id=token.client_id,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            expires_at=token.expires_at,
            scope=token.scope,
            token_type=token.token_type,
        )
        self.accounts_by_account_id[account_id] = record
        return record

    async def update_account(self, account: TwitchAccountUpdate) -> TwitchAccountRecord | None:
        existing = self.accounts_by_account_id.get(account.account_id)
        if existing is None:
            return None
        token = account.token
        updated = TwitchAccountRecord(
            account_id=account.account_id,
            discord_user_id=existing.discord_user_id,
            twitch_user_id=token.twitch_user_id,
            twitch_login=token.twitch_login,
            client_id=token.client_id,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            expires_at=token.expires_at,
            scope=token.scope,
            token_type=token.token_type,
        )
        self.accounts_by_account_id[account.account_id] = updated
        return updated

    async def remove_by_account_id(self, account_id: int) -> bool:
        return self.accounts_by_account_id.pop(account_id, None) is not None

    async def get_by_discord_user_id(self, discord_user_id: int) -> TwitchAccountRecord | None:
        matches = [account for account in self.accounts_by_account_id.values() if account.discord_user_id == discord_user_id]
        if not matches:
            return None
        return sorted(matches, key=lambda account: account.account_id)[-1]

    async def upsert_account(self, account: TwitchAccountCreate) -> TwitchAccountRecord:
        existing = await self.get_by_discord_user_id(account.discord_user_id)
        if existing is None:
            return await self.create_account(account)
        updated = await self.update_account(
            TwitchAccountUpdate(
                account_id=existing.account_id,
                token=account.token,
            )
        )
        assert updated is not None
        return updated

    async def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        existing = await self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return await self.remove_by_account_id(existing.account_id)


def _account_create(
    *,
    discord_user_id: int = 200,
    twitch_user_id: str = "77",
    twitch_login: str = "dancedown",
    client_id: str = "client-123",
    access_token: str = "oauth:test-token",
    refresh_token: str | None = None,
    expires_at: str | None = None,
    scope: tuple[str, ...] = ("user:write:chat",),
    token_type: str | None = "bearer",
) -> TwitchAccountCreate:
    return TwitchAccountCreate(
        discord_user_id=discord_user_id,
        token=TwitchAccountTokenData(
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login,
            client_id=client_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            token_type=token_type,
        ),
    )


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
class FakeTwitchAPI(TwitchWriteGateway):
    users_by_login: dict[str, TwitchUser] = field(default_factory=dict)
    sent_messages: list[dict[str, str | None]] = field(default_factory=list)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        return self.users_by_login[login.strip().lower()]

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        return await self.get_user_by_login(login)

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        for user in self.users_by_login.values():
            if user.user_id == user_id:
                return user
        raise KeyError(user_id)

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart:
        raise NotImplementedError

    async def poll_device_code_flow(
        self,
        *,
        device_code: str,
        scopes: tuple[str, ...],
    ) -> TwitchDevicePollResult:
        raise NotImplementedError

    async def send_chat_message(self, request: TwitchChatSendRequest) -> str:
        self.sent_messages.append(
            {
                "access_token": request.access_token,
                "client_id": request.client_id,
                "sender_id": request.sender_id,
                "broadcaster_id": request.broadcaster_id,
                "message": request.message,
                "reply_parent_message_id": request.reply_parent_message_id,
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
        _ = access_token
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
    bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    account_repository = InMemoryAccountRepository()
    account = await account_repository.create_account(_account_create())
    await thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    bus.write = TwitchWriteCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
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
    bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    account_repository = InMemoryAccountRepository()
    account = await account_repository.create_account(_account_create())
    await thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    bus.write = TwitchWriteCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
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
    bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    permission_repository = InMemoryPermissionRepository()
    account_repository = InMemoryAccountRepository()
    account = await account_repository.create_account(_account_create(access_token="oauth:owner-token"))
    await thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    bus.permission = PermissionCommandService(
        thread_repository=thread_repository,
        permission_repository=permission_repository,
    )
    bus.write = TwitchWriteCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
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
    bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(1, "42")
    permission_repository = InMemoryPermissionRepository()
    account_repository = InMemoryAccountRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    bus.permission = PermissionCommandService(
        thread_repository=thread_repository,
        permission_repository=permission_repository,
    )
    bus.write = TwitchWriteCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
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
