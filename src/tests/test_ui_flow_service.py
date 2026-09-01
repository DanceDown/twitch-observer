from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.database.connection import (
    ChannelRecord,
    PatternRepository,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
    UserPermissionRepository,
)
from src.events.ui_flow import RequestUIFlowCommand, UIFlowKind, UIFlowStep
from src.services.ui_flow_service import DiscordUIFlowGuardService
from src.tests.in_memory_channels import InMemoryChannelRepository as BaseInMemoryChannelRepository


@dataclass
class InMemoryThreadRepository(ThreadRepository):
    threads_by_channel_id: dict[int, ThreadRecord] = field(default_factory=dict)

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.get(discord_channel_id)

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        return next((thread for thread in self.threads_by_channel_id.values() if thread.thread_id == thread_id), None)

    async def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
        thread = ThreadRecord(thread_id=1, owner_id=owner_id, discord_channel_id=discord_channel_id, enabled=True, color=None)
        self.threads_by_channel_id[discord_channel_id] = thread
        return thread


@dataclass
class InMemoryChannelRepository(BaseInMemoryChannelRepository):
    channels: list[ChannelRecord] = field(default_factory=list)

    async def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        if self.channels:
            return [channel for channel in self.channels if channel.thread_id == thread_id]
        return await super().list_channels_for_thread(thread_id)


class EmptyPatternRepository(PatternRepository):
    pass


class EmptyReplyRepository(ReplyRepository):
    pass


class EmptyAccountRepository(TwitchAccountRepository):
    async def get_by_account_id(self, account_id: int):
        _ = account_id
        return


class EmptyPermissionRepository(UserPermissionRepository):
    async def get_by_user_and_thread(self, *, discord_user_id: int, thread_id: int):
        _ = discord_user_id, thread_id
        return


@pytest.mark.asyncio
async def test_ui_flow_guard_returns_not_joined_before_opening_ui() -> None:
    service = DiscordUIFlowGuardService(
        thread_repository=InMemoryThreadRepository(),
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await service.decide(
        RequestUIFlowCommand(
            discord_channel_id=100,
            requester_id=200,
            flow=UIFlowKind.CHANNEL,
            step=UIFlowStep.ROOT,
        ),
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "join" in decision.result.message


@pytest.mark.asyncio
async def test_ui_flow_guard_prioritizes_permission_over_empty_ping_state() -> None:
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    service = DiscordUIFlowGuardService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await service.decide(
        RequestUIFlowCommand(
            discord_channel_id=100,
            requester_id=201,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.REMOVE,
        ),
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "permission" in decision.result.title.lower()


@pytest.mark.asyncio
async def test_ui_flow_guard_allows_owner_to_open_leave_modal() -> None:
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    service = DiscordUIFlowGuardService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await service.decide(
        RequestUIFlowCommand(
            discord_channel_id=100,
            requester_id=200,
            flow=UIFlowKind.THREAD,
            step=UIFlowStep.LEAVE,
        ),
    )

    assert decision.open_ui is True
    assert decision.result is None


@pytest.mark.asyncio
async def test_ui_flow_guard_blocks_thread_color_modal_without_permission() -> None:
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    service = DiscordUIFlowGuardService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await service.decide(
        RequestUIFlowCommand(
            discord_channel_id=100,
            requester_id=201,
            flow=UIFlowKind.THREAD,
            step=UIFlowStep.COLOR,
        ),
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "permission" in decision.result.title.lower()


@pytest.mark.asyncio
async def test_ui_flow_guard_blocks_show_modal_without_view_permission() -> None:
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    service = DiscordUIFlowGuardService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await service.decide(
        RequestUIFlowCommand(
            discord_channel_id=100,
            requester_id=201,
            flow=UIFlowKind.SHOW,
            step=UIFlowStep.ROOT,
        ),
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "permission" in decision.result.title.lower()


@pytest.mark.asyncio
async def test_ui_flow_guard_blocks_reply_add_modal_without_linked_account() -> None:
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    service = DiscordUIFlowGuardService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await service.decide(
        RequestUIFlowCommand(
            discord_channel_id=100,
            requester_id=200,
            flow=UIFlowKind.REPLY,
            step=UIFlowStep.ADD_PATTERN,
        ),
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "account" in decision.result.title.lower()
