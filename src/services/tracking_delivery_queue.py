"""Ordered Discord tracking delivery for parallel chat processing."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field

import discord

from src.services.chat_delivery_context import ChatMessageCompletionNotifier, get_current_chat_message_sequence
from src.services.patterns import TrackingNotificationSender

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _TrackingDelivery:
    discord_channel_id: int
    embed: discord.Embed
    channel_login: str | None


@dataclass(slots=True)
class _MessageState:
    routing_complete: bool = False
    completed: bool = False


@dataclass(slots=True)
class _MessageSlot:
    deliveries: list[_TrackingDelivery] = field(default_factory=list)


@dataclass(slots=True)
class OrderedTrackingDeliveryService(TrackingNotificationSender, ChatMessageCompletionNotifier):
    """Deliver prepared tracking embeds in Twitch chat order per Discord thread."""

    sender: TrackingNotificationSender | None = None
    stop_timeout_seconds: float = 30
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition, init=False)
    _message_states: dict[int, _MessageState] = field(default_factory=dict, init=False)
    _slots_by_key: dict[int, dict[int, _MessageSlot]] = field(default_factory=dict, init=False)
    _next_sequence_by_key: dict[int, int] = field(default_factory=dict, init=False)
    _stop_requested: bool = field(default=False, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_requested = False
        self._task = asyncio.create_task(self._run_loop(), name="tracking-delivery-queue")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        async with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
        try:
            await asyncio.wait_for(task, timeout=max(0.1, self.stop_timeout_seconds))
        except TimeoutError:
            logger.warning("Tracking delivery queue did not drain in time; cancelling remaining delivery work.")
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            async with self._condition:
                self._message_states.clear()
                self._slots_by_key.clear()
                self._next_sequence_by_key.clear()
                self._stop_requested = False
            self._task = None

    async def reserve_message(self, sequence: int) -> None:
        async with self._condition:
            self._message_states.setdefault(sequence, _MessageState())
            self._condition.notify_all()

    async def complete_message_routing(self, sequence: int) -> None:
        async with self._condition:
            state = self._message_states.setdefault(sequence, _MessageState())
            state.routing_complete = True
            self._condition.notify_all()

    async def complete_message(self, sequence: int) -> None:
        async with self._condition:
            state = self._message_states.setdefault(sequence, _MessageState())
            state.routing_complete = True
            state.completed = True
            self._prune_message_states_locked()
            self._condition.notify_all()

    async def reserve_tracking_delivery(self, *, thread_id: int) -> None:
        sequence = get_current_chat_message_sequence()
        if sequence is None or self._task is None:
            return
        async with self._condition:
            self._reserve_slot_locked(ordering_key=thread_id, sequence=sequence)
            self._condition.notify_all()

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        sequence = get_current_chat_message_sequence()
        if sequence is None or self._task is None:
            await self._send_direct(discord_channel_id, embed, channel_login=channel_login)
            return
        ordering_key = self._ordering_key(thread_id=thread_id, discord_channel_id=discord_channel_id)
        async with self._condition:
            slot = self._reserve_slot_locked(ordering_key=ordering_key, sequence=sequence)
            slot.deliveries.append(
                _TrackingDelivery(
                    discord_channel_id=discord_channel_id,
                    embed=embed,
                    channel_login=channel_login,
                )
            )
            self._condition.notify_all()

    async def _run_loop(self) -> None:
        while True:
            async with self._condition:
                await self._condition.wait_for(lambda: (self._stop_requested and not self._slots_by_key) or self._has_ready_slot())
                if self._stop_requested and not self._slots_by_key:
                    return
                deliveries = self._take_ready_deliveries()
            for delivery in deliveries:
                try:
                    await self._send_direct(
                        delivery.discord_channel_id,
                        delivery.embed,
                        channel_login=delivery.channel_login,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Tracking delivery failed discord_channel_id=%s channel_login=%s.",
                        delivery.discord_channel_id,
                        delivery.channel_login,
                    )

    def _reserve_slot_locked(self, *, ordering_key: int, sequence: int) -> _MessageSlot:
        self._message_states.setdefault(sequence, _MessageState())
        slots = self._slots_by_key.setdefault(ordering_key, {})
        slot = slots.setdefault(sequence, _MessageSlot())
        current_next_sequence = self._next_sequence_by_key.get(ordering_key)
        if current_next_sequence is None or sequence < current_next_sequence:
            self._next_sequence_by_key[ordering_key] = sequence
        return slot

    def _has_ready_slot(self) -> bool:
        return any(self._is_group_ready(ordering_key) for ordering_key in self._next_sequence_by_key)

    def _take_ready_deliveries(self) -> list[_TrackingDelivery]:
        deliveries: list[_TrackingDelivery] = []
        for ordering_key in sorted(tuple(self._next_sequence_by_key)):
            while self._is_group_ready(ordering_key):
                next_sequence = self._next_sequence_by_key[ordering_key]
                slots = self._slots_by_key[ordering_key]
                slot = slots[next_sequence]
                deliveries.extend(slot.deliveries)
                del slots[next_sequence]
                if slots:
                    self._next_sequence_by_key[ordering_key] = min(slots)
                else:
                    self._slots_by_key.pop(ordering_key, None)
                    self._next_sequence_by_key.pop(ordering_key, None)
                    break
        self._prune_message_states_locked()
        return deliveries

    def _is_group_ready(self, ordering_key: int) -> bool:
        next_sequence = self._next_sequence_by_key.get(ordering_key)
        if next_sequence is None:
            return False
        slots = self._slots_by_key.get(ordering_key)
        if not slots or next_sequence not in slots:
            return False
        state = self._message_states.get(next_sequence)
        return state is not None and state.completed and self._earlier_routing_complete(next_sequence)

    def _earlier_routing_complete(self, sequence: int) -> bool:
        return all(known_sequence >= sequence or state.routing_complete for known_sequence, state in self._message_states.items())

    def _prune_message_states_locked(self) -> None:
        min_pending_sequence = min((sequence for slots in self._slots_by_key.values() for sequence in slots), default=None)
        for sequence, state in tuple(self._message_states.items()):
            if not state.completed or not state.routing_complete:
                continue
            if min_pending_sequence is None or sequence < min_pending_sequence:
                self._message_states.pop(sequence, None)

    @staticmethod
    def _ordering_key(*, thread_id: int | None, discord_channel_id: int) -> int:
        return thread_id if thread_id is not None else discord_channel_id

    async def _send_direct(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None,
    ) -> None:
        if self.sender is None:
            return
        await self.sender.send_tracking_embed(discord_channel_id, embed, channel_login=channel_login)
