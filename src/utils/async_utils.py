"""Small helpers for mixed sync/async collaborator compatibility."""

from __future__ import annotations

import inspect
from typing import TypeVar


T = TypeVar("T")


async def resolve_awaitable(value: T) -> T:
    """Await one value if it is awaitable, otherwise return it unchanged."""
    if inspect.isawaitable(value):
        return await value  # type: ignore[return-value]
    return value
