from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.events.event_types import TwitchChannelLiveStateChangedEvent, TwitchChatMessageEvent
from src.services.chat import ChatMessageReactionService
from src.services.chat_pipeline import ChatMessageProcessingService
from src.services.live_state_orchestrator import LiveStateChangeOrchestrator


@dataclass
class _Recorder:
    calls: list[str] = field(default_factory=list)


@dataclass
class _MessageIngest:
    recorder: _Recorder

    async def handle_chat_message(self, message: TwitchChatMessageEvent) -> None:
        self.recorder.calls.append(f"ingest:{message.content}")


@dataclass
class _UserObserver:
    recorder: _Recorder

    async def handle_chat_message(self, message: TwitchChatMessageEvent) -> None:
        self.recorder.calls.append(f"user:{message.author_login}")


@dataclass
class _ChatReactions:
    recorder: _Recorder

    async def handle_chat_message(self, message: TwitchChatMessageEvent) -> None:
        self.recorder.calls.append(f"react:{message.channel_login}:{message.message_id}")


@dataclass
class _LivePersistence:
    recorder: _Recorder

    async def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None:
        self.recorder.calls.append(f"persist:{event.twitch_channel_id}:{event.is_live}")


@dataclass
class _LiveNotification:
    recorder: _Recorder

    async def handle_change(
        self,
        event: TwitchChannelLiveStateChangedEvent,
        *,
        suppressed_events: set[tuple[int, int]] | None = None,
    ) -> None:
        self.recorder.calls.append(f"notify:{event.twitch_channel_id}")


@dataclass
class _LiveAutoReply:
    recorder: _Recorder

    async def handle_channel_live_state_changed(self, event: TwitchChannelLiveStateChangedEvent) -> set[tuple[int, int]]:
        self.recorder.calls.append(f"auto-reply:{event.changed_at}")
        return set()


@pytest.mark.asyncio
async def test_chat_pipeline_runs_in_explicit_order() -> None:
    recorder = _Recorder()
    pipeline = ChatMessageProcessingService(
        message_ingest=_MessageIngest(recorder),
        user_observer=_UserObserver(recorder),
        reactions=_ChatReactions(recorder),  # type: ignore[arg-type]
    )

    await pipeline.process(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            content="hello",
            message_id="m-1",
        )
    )

    assert recorder.calls == [
        "ingest:hello",
        "user:alice",
        "react:example:m-1",
    ]


@pytest.mark.asyncio
async def test_live_state_orchestrator_runs_in_explicit_order() -> None:
    recorder = _Recorder()
    orchestrator = LiveStateChangeOrchestrator(
        persistence=_LivePersistence(recorder),
        notifications=_LiveNotification(recorder),
        auto_replies=_LiveAutoReply(recorder),
    )

    await orchestrator.handle_change(
        TwitchChannelLiveStateChangedEvent(
            twitch_channel_id="42",
            twitch_channel_login="example",
            is_live=True,
            changed_at="now",
        )
    )

    assert recorder.calls == [
        "persist:42:True",
        "auto-reply:now",
        "notify:42",
    ]
