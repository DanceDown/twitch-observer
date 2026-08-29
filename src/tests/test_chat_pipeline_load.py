from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

import discord
import pytest

from src.events.twitch_events import TwitchChatMessageEvent
from src.services.chat_pipeline import ChatMessageProcessingService
from src.services.patterns import TrackingNotificationSender
from src.services.tracking_delivery_queue import OrderedTrackingDeliveryService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LOAD_TESTS") != "1",
    reason="set RUN_LOAD_TESTS=1 to run developer load tests",
)


@dataclass
class _LoadMessageIngest:
    handled: int = 0

    async def handle_chat_message(self, message: TwitchChatMessageEvent) -> None:
        self.handled += 1


@dataclass
class _LoadUserObserver:
    handled: int = 0

    async def handle_chat_message(self, message: TwitchChatMessageEvent) -> None:
        self.handled += 1


@dataclass
class _LoadSender(TrackingNotificationSender):
    send_delay_seconds: float
    sent: list[int] = field(default_factory=list)

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        _ = discord_channel_id, channel_login, thread_id
        if self.send_delay_seconds > 0:
            await asyncio.sleep(self.send_delay_seconds)
        self.sent.append(int(embed.title or "0"))


@dataclass
class _LoadReactions:
    notifier: TrackingNotificationSender
    match_every: int
    slow_every: int
    lookup_delay_seconds: float
    active: int = 0
    max_active: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def handle_chat_message(self, message: TwitchChatMessageEvent) -> None:
        message_index = int((message.message_id or "m-0").removeprefix("m-"))
        async with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.slow_every > 0 and message_index % self.slow_every == 0:
                await asyncio.sleep(self.lookup_delay_seconds)
            if message_index % self.match_every == 0:
                await self.notifier.send_tracking_embed(
                    1000,
                    discord.Embed(title=str(message_index)),
                    channel_login=message.channel_login,
                    thread_id=1,
                )
        finally:
            async with self._lock:
                self.active -= 1


@pytest.mark.asyncio
async def test_chat_pipeline_load_preserves_delivery_order_after_parallel_processing() -> None:
    message_count = _env_int("LOAD_TEST_MESSAGES", 1000)
    worker_count = _env_int("LOAD_TEST_WORKERS", 8)
    match_every = max(1, _env_int("LOAD_TEST_MATCH_EVERY", 1))
    slow_every = max(0, _env_int("LOAD_TEST_SLOW_EVERY", 3))
    lookup_delay_seconds = _env_float("LOAD_TEST_LOOKUP_DELAY_SECONDS", 0.005)
    send_delay_seconds = _env_float("LOAD_TEST_SEND_DELAY_SECONDS", 0)
    max_seconds = _env_float("LOAD_TEST_MAX_SECONDS", 10)

    sender = _LoadSender(send_delay_seconds=send_delay_seconds)
    delivery_queue = OrderedTrackingDeliveryService(sender=sender, stop_timeout_seconds=max_seconds)
    reactions = _LoadReactions(
        notifier=delivery_queue,
        match_every=match_every,
        slow_every=slow_every,
        lookup_delay_seconds=lookup_delay_seconds,
    )
    pipeline = ChatMessageProcessingService(
        message_ingest=_LoadMessageIngest(),
        user_observer=_LoadUserObserver(),
        reactions=reactions,  # type: ignore[arg-type]
        queue_size=message_count + worker_count,
        worker_count=worker_count,
        completion_notifier=delivery_queue,
    )

    started_at = time.perf_counter()
    await delivery_queue.start()
    await pipeline.start()
    try:
        for message_index in range(1, message_count + 1):
            await pipeline.enqueue(
                TwitchChatMessageEvent(
                    channel_login="example",
                    author_login=f"user-{message_index}",
                    author_id=str(message_index),
                    broadcaster_id="42",
                    content=f"message {message_index}",
                    message_id=f"m-{message_index}",
                )
            )
        await pipeline.stop()
        await delivery_queue.stop()
    finally:
        await pipeline.stop()
        await delivery_queue.stop()

    elapsed_seconds = time.perf_counter() - started_at
    expected_sent = [message_index for message_index in range(1, message_count + 1) if message_index % match_every == 0]
    print(
        "load-test "
        f"messages={message_count} workers={worker_count} sent={len(sender.sent)} "
        f"max_active={reactions.max_active} elapsed_seconds={elapsed_seconds:.3f}"
    )
    assert sender.sent == expected_sent
    if worker_count > 1 and slow_every > 0 and lookup_delay_seconds > 0 and message_count > slow_every:
        assert reactions.max_active > 1
    assert elapsed_seconds < max_seconds


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))
