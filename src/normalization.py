"""Central input normalization helpers used across services and entrypoints."""

from __future__ import annotations

import re

from src.errors import InputNormalizationError

_HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def normalize_twitch_login(value: str) -> str:
    """Normalize one Twitch login for lookups and persistence."""
    normalized = value.strip().lower()
    if not normalized:
        raise InputNormalizationError.missing_twitch_login()
    return normalized


def normalize_twitch_user_id(value: str) -> str:
    """Normalize one Twitch user ID for lookups and persistence."""
    normalized = value.strip()
    if not normalized:
        raise InputNormalizationError.missing_twitch_user_id()
    return normalized


def normalize_discord_channel_id(value: int | None) -> int:
    """Require one Discord channel/context ID."""
    if value is None:
        raise InputNormalizationError.missing_discord_channel_id()
    return value


def normalize_language(value: str) -> str:
    """Normalize one thread language key."""
    normalized = value.strip().lower()
    if not normalized:
        raise InputNormalizationError.missing_language()
    return normalized


def normalize_optional_color(value: str | None) -> str | None:
    """Normalize one optional hex color value."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not _HEX_COLOR_RE.fullmatch(normalized):
        raise InputNormalizationError.invalid_hex_color()
    return normalized


def normalize_required_text(value: str, *, field_name: str, max_length: int | None = None) -> str:
    """Normalize one required free-text field."""
    normalized = value.strip()
    if not normalized:
        raise InputNormalizationError.empty_text_field(field_name)
    if max_length is not None and len(normalized) > max_length:
        raise InputNormalizationError.text_field_too_long(field_name)
    return normalized
