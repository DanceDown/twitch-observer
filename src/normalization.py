"""Central input normalization helpers used across services and entrypoints."""

from __future__ import annotations

import re


_HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def normalize_twitch_login(value: str) -> str:
    """Normalize one Twitch login for lookups and persistence."""
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Missing Twitch login.")
    return normalized


def normalize_twitch_user_id(value: str) -> str:
    """Normalize one Twitch user ID for lookups and persistence."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("Missing Twitch user ID.")
    return normalized


def normalize_discord_channel_id(value: int | None) -> int:
    """Require one Discord channel/context ID."""
    if value is None:
        raise ValueError("Missing Discord channel ID.")
    return value


def normalize_language(value: str) -> str:
    """Normalize one thread language key."""
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Missing language.")
    return normalized


def normalize_optional_color(value: str | None) -> str | None:
    """Normalize one optional hex color value."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not _HEX_COLOR_RE.fullmatch(normalized):
        raise ValueError("Color must use #RRGGBB.")
    return normalized


def normalize_required_text(value: str, *, field_name: str, max_length: int | None = None) -> str:
    """Normalize one required free-text field."""
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    if max_length is not None and len(normalized) > max_length:
        raise ValueError(f"{field_name} is too long.")
    return normalized
