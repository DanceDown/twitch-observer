from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.events.twitch_events import TwitchChannelLiveStateChangedEvent, TwitchChatMessageEvent
from src.services.chat_pipeline import ChatMessageProcessingService
from src.services.live_state_orchestrator import LiveStateChangeOrchestrator


async def _wait_until(predicate, *, timeout: float = 1) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError
        await asyncio.sleep(0.01)


@dataclass
class _Recorder:
    calls: list[str] = field(default_factory=list)


@dataclass
class _CompletionRecorder:
    reserved: list[int] = field(default_factory=list)
    completed: list[int] = field(default_factory=list)

    async def reserve_message(self, sequence: int) -> None:
        self.reserved.append(sequence)

    async def complete_message(self, sequence: int) -> None:
        self.completed.append(sequence)


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
class _BlockingChatReactions:
    recorder: _Recorder
    first_started: asyncio.Event = field(default_factory=asyncio.Event)
    release_first: asyncio.Event = field(default_factory=asyncio.Event)

    async def handle_chat_message(self, message: TwitchChatMessageEvent) -> None:
        self.recorder.calls.append(f"react-start:{message.message_id}")
        if message.message_id == "m-1":
            self.first_started.set()
            await self.release_first.wait()
        self.recorder.calls.append(f"react:{message.message_id}")


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
async def test_chat_pipeline_workers_drain_queued_messages() -> None:
    recorder = _Recorder()
    completion_recorder = _CompletionRecorder()
    pipeline = ChatMessageProcessingService(
        message_ingest=_MessageIngest(recorder),
        user_observer=_UserObserver(recorder),
        reactions=_ChatReactions(recorder),  # type: ignore[arg-type]
        queue_size=10,
        worker_count=1,
        completion_notifier=completion_recorder,
    )

    await pipeline.start()
    await pipeline.enqueue(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            content="first",
            message_id="m-1",
        )
    )
    await pipeline.enqueue(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="bob",
            content="second",
            message_id="m-2",
        )
    )
    await asyncio.wait_for(pipeline.stop(), timeout=1)

    assert recorder.calls == [
        "ingest:first",
        "user:alice",
        "react:example:m-1",
        "ingest:second",
        "user:bob",
        "react:example:m-2",
    ]
    assert completion_recorder.reserved == [1, 2]
    assert completion_recorder.completed == [1, 2]


@pytest.mark.asyncio
async def test_chat_pipeline_waits_for_in_flight_reply_parent_only() -> None:
    recorder = _Recorder()
    reactions = _BlockingChatReactions(recorder)
    pipeline = ChatMessageProcessingService(
        message_ingest=_MessageIngest(recorder),
        user_observer=_UserObserver(recorder),
        reactions=reactions,  # type: ignore[arg-type]
        queue_size=10,
        worker_count=3,
    )

    await pipeline.start()
    try:
        await pipeline.enqueue(
            TwitchChatMessageEvent(
                channel_login="example",
                author_login="alice",
                content="first",
                message_id="m-1",
            )
        )
        await asyncio.wait_for(reactions.first_started.wait(), timeout=1)
        await pipeline.enqueue(
            TwitchChatMessageEvent(
                channel_login="example",
                author_login="bob",
                content="reply",
                message_id="m-2",
                reply_parent_message_id="m-1",
            )
        )
        await pipeline.enqueue(
            TwitchChatMessageEvent(
                channel_login="example",
                author_login="carol",
                content="third",
                message_id="m-3",
            )
        )

        await _wait_until(lambda: "react:m-3" in recorder.calls)
        assert "ingest:reply" not in recorder.calls
        assert "react-start:m-2" not in recorder.calls

        reactions.release_first.set()
        await asyncio.wait_for(pipeline.stop(), timeout=1)

        assert recorder.calls.index("react:m-1") < recorder.calls.index("ingest:reply")
        assert recorder.calls.index("react:m-3") < recorder.calls.index("ingest:reply")
    finally:
        reactions.release_first.set()
        await pipeline.stop()


@pytest.mark.asyncio
async def test_chat_pipeline_stop_cancels_workers_after_timeout() -> None:
    recorder = _Recorder()
    reactions = _BlockingChatReactions(recorder)
    pipeline = ChatMessageProcessingService(
        message_ingest=_MessageIngest(recorder),
        user_observer=_UserObserver(recorder),
        reactions=reactions,  # type: ignore[arg-type]
        queue_size=10,
        worker_count=1,
        stop_timeout_seconds=0.01,
    )

    await pipeline.start()
    await pipeline.enqueue(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            content="first",
            message_id="m-1",
        )
    )
    await asyncio.wait_for(reactions.first_started.wait(), timeout=1)

    await asyncio.wait_for(pipeline.stop(), timeout=1)

    assert pipeline._workers is None


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
