"""State and identifier helpers for pattern command entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

import discord

from src.events.pattern_scopes import ChannelScopeMode, OfflineScope, SubscriptionScope, UserScopeMode

from ..helpers import normalize_optional_text, split_csv_values
from ..ui.patterns.state import PatternFormState
from ..ui_data import DiscordUIDataProvider


@dataclass(slots=True, frozen=True)
class PatternAddCommandOptions:
    """Slash-command option group used to seed the ping add form or direct command."""

    pattern_text: str | None
    is_regex: bool
    channel_scope_mode: discord.app_commands.Choice[str] | None
    channel_logins: str | None
    user_scope_mode: discord.app_commands.Choice[str] | None
    user_logins: str | None
    sub_state: discord.app_commands.Choice[str] | None
    offline_state: discord.app_commands.Choice[str] | None
    case_sensitive: bool
    color: str | None
    priority: int | None
    disabled: bool


@dataclass(slots=True, frozen=True)
class PatternEditCommandOptions:
    """Slash-command option group used to seed or execute ping edits."""

    pattern_id: int | None
    pattern_text: str | None
    is_regex: bool | None
    channel_scope_mode: discord.app_commands.Choice[str] | None
    channel_logins: str | None
    user_scope_mode: discord.app_commands.Choice[str] | None
    user_logins: str | None
    sub_state: discord.app_commands.Choice[str] | None
    offline_state: discord.app_commands.Choice[str] | None
    case_sensitive: bool | None
    color: str | None
    clear_color: bool
    priority: int | None


@dataclass(slots=True, frozen=True)
class _ScopedOverrideSpec:
    mode_key: str
    selected_key: str
    name_key: str
    default_selected_mode: str


_CHANNEL_SCOPE_OVERRIDE = _ScopedOverrideSpec(
    mode_key="channel_scope_mode",
    selected_key="selected_channels",
    name_key="selected_channel_names",
    default_selected_mode=ChannelScopeMode.ONLY_SELECTED.value,
)
_USER_SCOPE_OVERRIDE = _ScopedOverrideSpec(
    mode_key="user_scope_mode",
    selected_key="selected_users",
    name_key="selected_user_names",
    default_selected_mode=UserScopeMode.ONLY_SELECTED.value,
)


async def resolve_pattern_identifier(
    ui_data_provider: DiscordUIDataProvider,
    discord_channel_id: int,
    pattern_id: int,
) -> int:
    """Resolve either a real pattern ID or a visible display index."""
    patterns = await ui_data_provider.list_patterns(discord_channel_id)
    for item in patterns:
        if item.pattern.pattern_id == pattern_id:
            return item.pattern.pattern_id
    for item in patterns:
        if item.display_index == pattern_id:
            return item.pattern.pattern_id
    return pattern_id


def build_pattern_add_state(
    options: PatternAddCommandOptions,
    *,
    normalized_pattern_text: str | None,
) -> PatternFormState:
    """Build the ping form state seeded from slash-command add options."""
    return PatternFormState(
        pattern_text=normalized_pattern_text,
        is_regex=options.is_regex,
        channel_scope_mode=resolved_channel_scope_mode(options.channel_scope_mode, options.channel_logins).value,
        selected_channels=list(split_csv_values(options.channel_logins)),
        selected_channel_names=list(split_csv_values(options.channel_logins)),
        user_scope_mode=resolved_user_scope_mode(options.user_scope_mode, options.user_logins).value,
        selected_users=list(split_csv_values(options.user_logins)),
        selected_user_names=list(split_csv_values(options.user_logins)),
        sub_state=options.sub_state.value if options.sub_state is not None else SubscriptionScope.ALL.value,
        offline_state=options.offline_state.value if options.offline_state is not None else OfflineScope.BOTH.value,
        case_sensitive=options.case_sensitive,
        color=normalize_optional_text(options.color),
        priority=options.priority,
    )


def build_pattern_edit_overrides(
    options: PatternEditCommandOptions,
    *,
    normalized_pattern_text: str | None,
    normalized_color: str | None,
) -> dict[str, object]:
    """Build sparse pattern edit overrides from provided slash-command options."""
    overrides: dict[str, object] = {}
    _set_if_present(overrides, "pattern_text", normalized_pattern_text)
    _set_if_present(overrides, "is_regex", options.is_regex)
    _apply_scoped_values(
        overrides,
        spec=_CHANNEL_SCOPE_OVERRIDE,
        choice=options.channel_scope_mode,
        raw_values=options.channel_logins,
    )
    _apply_scoped_values(
        overrides,
        spec=_USER_SCOPE_OVERRIDE,
        choice=options.user_scope_mode,
        raw_values=options.user_logins,
    )
    _set_choice_if_present(overrides, "sub_state", options.sub_state)
    _set_choice_if_present(overrides, "offline_state", options.offline_state)
    _set_if_present(overrides, "case_sensitive", options.case_sensitive)
    _apply_color_override(overrides, color=normalized_color, clear_color=options.clear_color)
    _set_if_present(overrides, "priority", options.priority)
    return overrides


def _set_if_present(overrides: dict[str, object], key: str, value: object | None) -> None:
    if value is not None:
        overrides[key] = value


def _set_choice_if_present(
    overrides: dict[str, object],
    key: str,
    choice: discord.app_commands.Choice[str] | None,
) -> None:
    if choice is not None:
        overrides[key] = choice.value


def _apply_scoped_values(
    overrides: dict[str, object],
    *,
    spec: _ScopedOverrideSpec,
    choice: discord.app_commands.Choice[str] | None,
    raw_values: str | None,
) -> None:
    if choice is not None:
        overrides[spec.mode_key] = choice.value
    elif raw_values is not None:
        overrides[spec.mode_key] = spec.default_selected_mode

    if raw_values is not None:
        selected_values = list(split_csv_values(raw_values))
        overrides[spec.selected_key] = selected_values
        overrides[spec.name_key] = list(selected_values)


def _apply_color_override(overrides: dict[str, object], *, color: str | None, clear_color: bool) -> None:
    if clear_color:
        overrides["color"] = None
    elif color is not None:
        overrides["color"] = color


def resolved_channel_scope_mode(
    channel_scope_mode: discord.app_commands.Choice[str] | None,
    channel_logins: str | None,
) -> ChannelScopeMode:
    """Infer the effective channel scope mode from choices and raw logins."""
    if channel_scope_mode is not None:
        return ChannelScopeMode(channel_scope_mode.value)
    if split_csv_values(channel_logins):
        return ChannelScopeMode.ONLY_SELECTED
    return ChannelScopeMode.ALL_TRACKED


def resolved_user_scope_mode(
    user_scope_mode: discord.app_commands.Choice[str] | None,
    user_logins: str | None,
) -> UserScopeMode:
    """Infer the effective user scope mode from choices and raw logins."""
    if user_scope_mode is not None:
        return UserScopeMode(user_scope_mode.value)
    if split_csv_values(user_logins):
        return UserScopeMode.ONLY_SELECTED
    return UserScopeMode.ALL_USERS
