"""Shared typed pattern scope definitions."""

from __future__ import annotations

from enum import StrEnum


class ChannelScopeMode(StrEnum):
    """Typed pattern channel scope selectors."""

    ALL_TRACKED = "all_tracked"
    ONLY_SELECTED = "only_selected"
    ALL_EXCEPT_SELECTED = "all_except_selected"


class UserScopeMode(StrEnum):
    """Typed pattern user scope selectors."""

    ALL_USERS = "all_users"
    ALL_TRACKED = "all_tracked"
    ONLY_SELECTED = "only_selected"
    ALL_EXCEPT_SELECTED = "all_except_selected"
    ALL_TRACKED_EXCEPT_SELECTED = "all_tracked_except_selected"


class SubscriptionScope(StrEnum):
    """Typed subscriber-state filters."""

    ALL = "all"
    NON_SUBS = "non_subs"
    SUBS = "subs"


class OfflineScope(StrEnum):
    """Typed live/offline filters."""

    BOTH = "both"
    OFFLINE = "offline"
    ONLINE = "online"
