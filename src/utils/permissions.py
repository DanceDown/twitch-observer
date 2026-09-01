"""Permission bitmask helpers for per-thread Discord authorization."""

from __future__ import annotations

from enum import IntFlag


class ObserverPermission(IntFlag):
    """Bitmask permissions that may be granted to non-owner Discord users."""

    VIEW = 1 << 0
    MANAGE_CHANNELS = 1 << 1
    TOGGLE_PATTERNS = 1 << 2
    MANAGE_PATTERNS = 1 << 3
    TOGGLE_REPLIES = 1 << 4
    MANAGE_REPLIES = 1 << 5
    SEND_TWITCH_MESSAGES = 1 << 6
    CONTROL_OBSERVER = 1 << 7
    LEAVE_CONTEXT = 1 << 8
    MANAGE_PERMISSIONS = 1 << 9
    ADMIN = 1 << 10


class UnsupportedPermissionError(ValueError):
    """Raised when a persisted or slash-command permission value is unknown."""

    def __init__(self, value: str) -> None:
        """Create the unsupported-permission error for one raw value."""
        super().__init__(f"Unsupported permission `{value}`.")


PERMISSION_CHOICES: tuple[tuple[str, ObserverPermission], ...] = (
    ("view", ObserverPermission.VIEW),
    ("manage_channels", ObserverPermission.MANAGE_CHANNELS),
    ("toggle_patterns", ObserverPermission.TOGGLE_PATTERNS),
    ("manage_patterns", ObserverPermission.MANAGE_PATTERNS),
    ("toggle_replies", ObserverPermission.TOGGLE_REPLIES),
    ("manage_replies", ObserverPermission.MANAGE_REPLIES),
    ("send_twitch_messages", ObserverPermission.SEND_TWITCH_MESSAGES),
    ("control_observer", ObserverPermission.CONTROL_OBSERVER),
    ("leave_context", ObserverPermission.LEAVE_CONTEXT),
    ("manage_permissions", ObserverPermission.MANAGE_PERMISSIONS),
    ("admin", ObserverPermission.ADMIN),
)

_ALL_PERMISSIONS = ObserverPermission(sum(int(permission) for _, permission in PERMISSION_CHOICES))
_IMPLIED_PERMISSIONS: tuple[tuple[ObserverPermission, ObserverPermission], ...] = (
    (ObserverPermission.MANAGE_CHANNELS, ObserverPermission.VIEW),
    (ObserverPermission.MANAGE_PATTERNS, ObserverPermission.TOGGLE_PATTERNS | ObserverPermission.VIEW),
    (ObserverPermission.TOGGLE_PATTERNS, ObserverPermission.VIEW),
    (ObserverPermission.MANAGE_REPLIES, ObserverPermission.TOGGLE_REPLIES | ObserverPermission.VIEW),
    (ObserverPermission.TOGGLE_REPLIES, ObserverPermission.VIEW),
    (ObserverPermission.SEND_TWITCH_MESSAGES, ObserverPermission.VIEW),
    (ObserverPermission.CONTROL_OBSERVER, ObserverPermission.VIEW),
    (ObserverPermission.LEAVE_CONTEXT, ObserverPermission.VIEW),
    (ObserverPermission.MANAGE_PERMISSIONS, ObserverPermission.VIEW),
)


def permission_from_value(value: str) -> ObserverPermission:
    """Map a stable slash-command choice value to one permission bit."""
    normalized = value.strip().lower()
    for raw_value, permission in PERMISSION_CHOICES:
        if raw_value == normalized:
            return permission
    raise UnsupportedPermissionError(value)


def permissions_mask_from_values(values: tuple[str, ...]) -> int:
    """Resolve multiple stable permission values into one bitmask."""
    mask = 0
    for value in values:
        mask |= int(permission_from_value(value))
    return mask


def explicit_permission_labels(mask: int) -> tuple[str, ...]:
    """Return the explicitly stored permission names for one bitmask."""
    resolved = []
    for value, permission in PERMISSION_CHOICES:
        if mask & int(permission):
            resolved.append(value)
    return tuple(resolved)


def effective_permissions(mask: int) -> ObserverPermission:
    """Expand a raw bitmask with the project's implied permission semantics."""
    permissions = ObserverPermission(mask)

    if permissions & ObserverPermission.ADMIN:
        return _ALL_PERMISSIONS

    for granted, implied in _IMPLIED_PERMISSIONS:
        if permissions & granted:
            permissions |= implied
    return permissions


def has_permission(mask: int, permission: ObserverPermission) -> bool:
    """Return whether the expanded permission set contains one required bit."""
    return bool(effective_permissions(mask) & permission)
