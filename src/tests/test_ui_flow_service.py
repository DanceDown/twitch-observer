from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.adapters.discord import dispatch_ui_flow_decision
from src.database.connection import (
    ChannelRecord,
    ChannelRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.services.ui_flow_service import DiscordUIFlowGuardService


@dataclass
class InMemoryThreadRepository(ThreadRepository):
    threads_by_channel_id: dict[int, ThreadRecord] = field(default_factory=dict)

    def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.get(discord_channel_id)

    def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        return next((thread for thread in self.threads_by_channel_id.values() if thread.thread_id == thread_id), None)

    def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
        thread = ThreadRecord(thread_id=1, owner_id=owner_id, discord_channel_id=discord_channel_id, enabled=True, color=None)
        self.threads_by_channel_id[discord_channel_id] = thread
        return thread


@dataclass
class InMemoryChannelRepository(ChannelRepository):
    channels: list[ChannelRecord] = field(default_factory=list)

    def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return [channel for channel in self.channels if channel.thread_id == thread_id]

    def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        return None


class EmptyPatternRepository(PatternRepository):
    pass


class EmptyReplyRepository(ReplyRepository):
    pass


class EmptyAccountRepository(TwitchAccountRepository):
    def get_by_account_id(self, account_id: int):
        return None


class EmptyPermissionRepository(UserPermissionRepository):
    def get_by_user_and_thread(self, *, discord_user_id: int, thread_id: int):
        return None


@pytest.mark.asyncio
async def test_ui_flow_guard_returns_not_joined_before_opening_ui() -> None:
    bus = EventBus()
    DiscordUIFlowGuardService(
        event_bus=bus,
        thread_repository=InMemoryThreadRepository(),
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await dispatch_ui_flow_decision(
        bus,
        discord_channel_id=100,
        requester_id=200,
        flow="channel",
        step="root",
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "join" in decision.result.message


@pytest.mark.asyncio
async def test_ui_flow_guard_prioritizes_permission_over_empty_ping_state() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    DiscordUIFlowGuardService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await dispatch_ui_flow_decision(
        bus,
        discord_channel_id=100,
        requester_id=201,
        flow="ping",
        step="remove",
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "permission" in decision.result.title.lower()


@pytest.mark.asyncio
async def test_ui_flow_guard_allows_owner_to_open_leave_modal() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    DiscordUIFlowGuardService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await dispatch_ui_flow_decision(
        bus,
        discord_channel_id=100,
        requester_id=200,
        flow="thread",
        step="leave",
    )

    assert decision.open_ui is True
    assert decision.result is None


@pytest.mark.asyncio
async def test_ui_flow_guard_blocks_thread_color_modal_without_permission() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    DiscordUIFlowGuardService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await dispatch_ui_flow_decision(
        bus,
        discord_channel_id=100,
        requester_id=201,
        flow="thread",
        step="color",
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "permission" in decision.result.title.lower()


@pytest.mark.asyncio
async def test_ui_flow_guard_blocks_show_modal_without_view_permission() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    DiscordUIFlowGuardService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        account_repository=EmptyAccountRepository(),
        permission_repository=EmptyPermissionRepository(),
    )

    decision = await dispatch_ui_flow_decision(
        bus,
        discord_channel_id=100,
        requester_id=201,
        flow="show",
        step="root",
    )

    assert decision.open_ui is False
    assert decision.result is not None
    assert "permission" in decision.result.title.lower()
