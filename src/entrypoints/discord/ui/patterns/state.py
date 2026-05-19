"""Shared state and local enums for the guided ping UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PatternEditorMode(StrEnum):
    """Top-level editor mode for one ping flow."""

    ADD = "add"
    EDIT = "edit"


class PatternActionKind(StrEnum):
    """ID-based ping actions available from the menu."""

    REMOVE = "remove"
    DISABLE = "disable"
    ENABLE = "enable"


@dataclass(slots=True)
class PatternFormState:
    """Mutable in-memory state for the guided ping add/edit flow."""

    pattern_id: int | None = None
    pattern_text: str | None = None
    is_regex: bool = False
    channel_scope_mode: str = "all_tracked"
    selected_channels: list[str] = field(default_factory=list)
    selected_channel_names: list[str] = field(default_factory=list)
    user_scope_mode: str = "all_users"
    selected_users: list[str] = field(default_factory=list)
    selected_user_names: list[str] = field(default_factory=list)
    sub_state: str = "all"
    offline_state: str = "both"
    case_sensitive: bool = False
    color: str | None = None
    priority: int | None = None
