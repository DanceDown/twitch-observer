"""Helpers for Discord select option windows."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from typing import TypeVar

MAX_SELECT_OPTIONS = 25

_T = TypeVar("_T")
_K = TypeVar("_K")


def window_with_included_items(
    items: Sequence[_T],
    *,
    key: Callable[[_T], _K],
    included_keys: Collection[_K],
    limit: int = MAX_SELECT_OPTIONS,
) -> list[_T]:
    """Return one limited item window that still includes requested items when possible."""
    if limit <= 0 or not items:
        return []

    required_keys = {item_key for item_key in included_keys if item_key is not None}
    window = list(items[:limit])
    window_keys = [key(item) for item in window]
    if not required_keys or len(items) <= limit:
        return window

    for item in items[limit:]:
        item_key = key(item)
        if item_key not in required_keys or item_key in window_keys:
            continue
        replace_index = next(
            (index for index in range(len(window) - 1, -1, -1) if window_keys[index] not in required_keys),
            None,
        )
        if replace_index is None:
            break
        window[replace_index] = item
        window_keys[replace_index] = item_key
    return window
