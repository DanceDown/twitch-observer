"""State and identifier helpers for pattern command entrypoints."""

from __future__ import annotations

import discord

from src.events.event_types import ChannelScopeMode, OfflineScope, SubscriptionScope, UserScopeMode

from ..helpers import normalize_optional_text, split_csv_values
from ..ui.patterns.state import PatternFormState
from ..ui_data import DiscordUIDataProvider


async def resolve_pattern_identifier(
    ui_data_provider: DiscordUIDataProvider,
    discord_channel_id: int,
    pattern_id: int,
) -> int:
    patterns = await ui_data_provider.list_patterns(discord_channel_id)
    for item in patterns:
        if item.pattern.pattern_id == pattern_id:
            return item.pattern.pattern_id
    for item in patterns:
        if item.display_index == pattern_id:
            return item.pattern.pattern_id
    return pattern_id


def build_pattern_add_state(
    *,
    pattern_text: str | None,
    is_regex: bool,
    channel_scope_mode: discord.app_commands.Choice[str] | None,
    channel_logins: str | None,
    user_scope_mode: discord.app_commands.Choice[str] | None,
    user_logins: str | None,
    sub_state: discord.app_commands.Choice[str] | None,
    offline_state: discord.app_commands.Choice[str] | None,
    case_sensitive: bool,
    color: str | None,
    priority: int | None,
) -> PatternFormState:
    return PatternFormState(
        pattern_text=pattern_text,
        is_regex=is_regex,
        channel_scope_mode=resolved_channel_scope_mode(channel_scope_mode, channel_logins).value,
        selected_channels=list(split_csv_values(channel_logins)),
        selected_channel_names=list(split_csv_values(channel_logins)),
        user_scope_mode=resolved_user_scope_mode(user_scope_mode, user_logins).value,
        selected_users=list(split_csv_values(user_logins)),
        selected_user_names=list(split_csv_values(user_logins)),
        sub_state=sub_state.value if sub_state is not None else SubscriptionScope.ALL.value,
        offline_state=offline_state.value if offline_state is not None else OfflineScope.BOTH.value,
        case_sensitive=case_sensitive,
        color=normalize_optional_text(color),
        priority=priority,
    )


def build_pattern_edit_overrides(
    *,
    pattern_text: str | None,
    is_regex: bool | None,
    channel_scope_mode: discord.app_commands.Choice[str] | None,
    channel_logins: str | None,
    user_scope_mode: discord.app_commands.Choice[str] | None,
    user_logins: str | None,
    sub_state: discord.app_commands.Choice[str] | None,
    offline_state: discord.app_commands.Choice[str] | None,
    case_sensitive: bool | None,
    color: str | None,
    clear_color: bool,
    priority: int | None,
) -> dict[str, object]:
    overrides: dict[str, object] = {}
    if pattern_text is not None:
        overrides["pattern_text"] = pattern_text
    if is_regex is not None:
        overrides["is_regex"] = is_regex
    if channel_scope_mode is not None:
        overrides["channel_scope_mode"] = channel_scope_mode.value
        if channel_logins is not None:
            selected_channels = list(split_csv_values(channel_logins))
            overrides["selected_channels"] = selected_channels
            overrides["selected_channel_names"] = list(selected_channels)
    elif channel_logins is not None:
        selected_channels = list(split_csv_values(channel_logins))
        overrides["channel_scope_mode"] = ChannelScopeMode.ONLY_SELECTED.value
        overrides["selected_channels"] = selected_channels
        overrides["selected_channel_names"] = list(selected_channels)
    if user_scope_mode is not None:
        overrides["user_scope_mode"] = user_scope_mode.value
        if user_logins is not None:
            selected_users = list(split_csv_values(user_logins))
            overrides["selected_users"] = selected_users
            overrides["selected_user_names"] = list(selected_users)
    elif user_logins is not None:
        selected_users = list(split_csv_values(user_logins))
        overrides["user_scope_mode"] = UserScopeMode.ONLY_SELECTED.value
        overrides["selected_users"] = selected_users
        overrides["selected_user_names"] = list(selected_users)
    if sub_state is not None:
        overrides["sub_state"] = sub_state.value
    if offline_state is not None:
        overrides["offline_state"] = offline_state.value
    if case_sensitive is not None:
        overrides["case_sensitive"] = case_sensitive
    if clear_color:
        overrides["color"] = None
    elif color is not None:
        overrides["color"] = color
    if priority is not None:
        overrides["priority"] = priority
    return overrides


def resolved_channel_scope_mode(
    channel_scope_mode: discord.app_commands.Choice[str] | None,
    channel_logins: str | None,
) -> ChannelScopeMode:
    if channel_scope_mode is not None:
        return ChannelScopeMode(channel_scope_mode.value)
    if split_csv_values(channel_logins):
        return ChannelScopeMode.ONLY_SELECTED
    return ChannelScopeMode.ALL_TRACKED


def resolved_user_scope_mode(
    user_scope_mode: discord.app_commands.Choice[str] | None,
    user_logins: str | None,
) -> UserScopeMode:
    if user_scope_mode is not None:
        return UserScopeMode(user_scope_mode.value)
    if split_csv_values(user_logins):
        return UserScopeMode.ONLY_SELECTED
    return UserScopeMode.ALL_USERS
