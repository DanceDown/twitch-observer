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
    slow_target_id: int | None = None
    slow_target_send_delay_seconds: float = 0
    sent: list[tuple[int, int]] = field(default_factory=list)

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        _ = channel_login, thread_id
        delay_seconds = self.send_delay_seconds
        if self.slow_target_id is not None and discord_channel_id == self.slow_target_id:
            delay_seconds = self.slow_target_send_delay_seconds
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        self.sent.append((discord_channel_id, int(embed.title or "0")))


@dataclass
class _LoadReactions:
    notifier: TrackingNotificationSender
    match_every: int
    slow_every: int
    lookup_delay_seconds: float
    target_count: int
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
                target_id = 1000 + ((message_index - 1) % max(1, self.target_count))
                await self.notifier.send_tracking_embed(
                    target_id,
                    discord.Embed(title=str(message_index)),
                    channel_login=message.channel_login,
                    thread_id=target_id,
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
    target_count = max(1, _env_int("LOAD_TEST_TARGETS", 1))
    slow_target_id = _env_int_or_none("LOAD_TEST_SLOW_TARGET_ID")
    slow_target_send_delay_seconds = _env_float("LOAD_TEST_SLOW_TARGET_SEND_DELAY_SECONDS", send_delay_seconds)
    per_target_rate_per_second = _env_float("LOAD_TEST_PER_TARGET_RATE_PER_SECOND", 0)
    per_target_burst = max(1, _env_int("LOAD_TEST_PER_TARGET_BURST", 5))
    max_seconds = _env_float("LOAD_TEST_MAX_SECONDS", 10)

    sender = _LoadSender(
        send_delay_seconds=send_delay_seconds,
        slow_target_id=slow_target_id,
        slow_target_send_delay_seconds=slow_target_send_delay_seconds,
    )
    delivery_queue = OrderedTrackingDeliveryService(
        sender=sender,
        stop_timeout_seconds=max_seconds,
        per_target_rate_per_second=per_target_rate_per_second,
        per_target_burst=per_target_burst,
    )
    reactions = _LoadReactions(
        notifier=delivery_queue,
        match_every=match_every,
        slow_every=slow_every,
        lookup_delay_seconds=lookup_delay_seconds,
        target_count=target_count,
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
        f"messages={message_count} workers={worker_count} targets={target_count} sent={len(sender.sent)} "
        f"max_active={reactions.max_active} rate={per_target_rate_per_second} elapsed_seconds={elapsed_seconds:.3f}"
    )
    sent_messages = [message_index for _, message_index in sender.sent]
    if target_count == 1:
        assert sent_messages == expected_sent
    else:
        assert sorted(sent_messages) == expected_sent
        for target_id in range(1000, 1000 + target_count):
            target_messages = [message_index for sent_target_id, message_index in sender.sent if sent_target_id == target_id]
            assert target_messages == sorted(target_messages)
    if worker_count > 1 and slow_every > 0 and lookup_delay_seconds > 0 and message_count > slow_every:
        assert reactions.max_active > 1
    assert elapsed_seconds < max_seconds


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_int_or_none(name: str) -> int | None:
    value = os.getenv(name)
    return None if value is None or not value.strip() else int(value)


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))
