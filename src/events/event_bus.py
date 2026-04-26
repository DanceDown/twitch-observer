"""Simple in-process event bus connecting adapters and services."""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from src.events.event_types import EventType

EventHandler = Callable[[Any], Any | Awaitable[Any]]
logger = logging.getLogger(__name__)


class EventBus:
    """Dispatch domain events to subscribed handlers.

    Adapters publish normalized events into the bus. Services subscribe to the
    event types they care about and keep the business logic out of the adapter
    layer. The bus itself stays intentionally small and synchronous in order to
    keep the event flow easy to reason about during the early project stages.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        self._subscribers[event_type].append(handler)

    async def publish(self, event_type: EventType, event: Any) -> None:
        """Publish an event and await async handlers when needed."""
        logger.debug("Publishing event %s to %d subscriber(s): %r", event_type, len(self._subscribers[event_type]), event)
        for handler in list(self._subscribers[event_type]):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "Subscriber %s failed while handling event %s; continuing with remaining subscriber(s).",
                    _handler_name(handler),
                    event_type.value,
                )

    def subscriber_count(self, event_type: EventType) -> int:
        """Return how many handlers currently listen to an event type."""
        return len(self._subscribers[event_type])


def _handler_name(handler: EventHandler) -> str:
    """Return a compact, useful name for debug and error logs."""
    owner = getattr(handler, "__self__", None)
    name = getattr(handler, "__name__", repr(handler))
    if owner is None:
        return name
    return f"{owner.__class__.__name__}.{name}"

