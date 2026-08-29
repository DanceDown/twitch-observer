from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import discord
import pytest

from src.services.patterns import TrackingNotificationSender
from src.services.chat_delivery_context import bind_chat_message_sequence, reset_chat_message_sequence
from src.services.tracking_delivery_queue import OrderedTrackingDeliveryService


@dataclass
class _FakeSender(TrackingNotificationSender):
    sent: list[tuple[int, str, str | None]] = field(default_factory=list)
    failing_titles: set[str] = field(default_factory=set)

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        _ = thread_id
        title = embed.title or ""
        if title in self.failing_titles:
            raise RuntimeError(f"Send failed for {title}")
        self.sent.append((discord_channel_id, title, channel_login))


async def _send_with_sequence(service: OrderedTrackingDeliveryService, sequence: int, title: str, *, thread_id: int = 1) -> None:
    token = bind_chat_message_sequence(sequence)
    try:
        await service.send_tracking_embed(
            1000 + sequence,
            discord.Embed(title=title),
            channel_login=f"channel-{sequence}",
            thread_id=thread_id,
        )
    finally:
        reset_chat_message_sequence(token)


async def _wait_for_titles(sender: _FakeSender, expected: list[str], *, timeout: float = 1) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while [title for _, title, _ in sender.sent] != expected:
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError([title for _, title, _ in sender.sent])
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_tracking_delivery_queue_sends_finished_messages_in_chat_order() -> None:
    sender = _FakeSender()
    service = OrderedTrackingDeliveryService(sender=sender, stop_timeout_seconds=1)
    await service.start()
    try:
        for sequence in range(1, 6):
            await service.reserve_message(sequence)

        await _send_with_sequence(service, 2, "two")
        await service.complete_message(2)
        await asyncio.sleep(0.02)
        assert sender.sent == []

        await _send_with_sequence(service, 1, "one")
        await service.complete_message(1)
        await _wait_for_titles(sender, ["one", "two"])

        await _send_with_sequence(service, 4, "four")
        await service.complete_message(4)
        await _send_with_sequence(service, 5, "five")
        await service.complete_message(5)
        await asyncio.sleep(0.02)
        assert [title for _, title, _ in sender.sent] == ["one", "two"]

        await _send_with_sequence(service, 3, "three")
        await service.complete_message(3)
        await _wait_for_titles(sender, ["one", "two", "three", "four", "five"])
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_tracking_delivery_queue_keeps_order_across_messages_without_embeds() -> None:
    sender = _FakeSender()
    service = OrderedTrackingDeliveryService(sender=sender, stop_timeout_seconds=1)
    await service.start()
    try:
        await service.reserve_message(1)
        await service.reserve_message(2)
        await _send_with_sequence(service, 2, "two")
        await service.complete_message(2)
        await asyncio.sleep(0.02)
        assert sender.sent == []

        await service.complete_message(1)
        await _wait_for_titles(sender, ["two"])
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_tracking_delivery_queue_continues_after_discord_send_failure() -> None:
    sender = _FakeSender(failing_titles={"one"})
    service = OrderedTrackingDeliveryService(sender=sender, stop_timeout_seconds=1)
    await service.start()
    try:
        await service.reserve_message(1)
        await service.reserve_message(2)
        await _send_with_sequence(service, 1, "one")
        await _send_with_sequence(service, 2, "two")

        await service.complete_message(1)
        await service.complete_message(2)

        await _wait_for_titles(sender, ["two"])
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_tracking_delivery_queue_sends_directly_when_not_started() -> None:
    sender = _FakeSender()
    service = OrderedTrackingDeliveryService(sender=sender)

    await service.send_tracking_embed(1000, discord.Embed(title="direct"), channel_login="example")

    assert sender.sent == [(1000, "direct", "example")]


@pytest.mark.asyncio
async def test_tracking_delivery_queue_orders_independently_per_thread_after_routing() -> None:
    sender = _FakeSender()
    service = OrderedTrackingDeliveryService(sender=sender, stop_timeout_seconds=1)
    await service.start()
    try:
        await service.reserve_message(1)
        await service.reserve_message(2)
        await _send_with_sequence(service, 1, "thread-one-slow", thread_id=1)
        await _send_with_sequence(service, 2, "thread-two-ready", thread_id=2)

        await service.complete_message_routing(1)
        await service.complete_message_routing(2)
        await service.complete_message(2)

        await _wait_for_titles(sender, ["thread-two-ready"])
        await service.complete_message(1)
        await _wait_for_titles(sender, ["thread-two-ready", "thread-one-slow"])
    finally:
        await service.stop()
