"""Typed dispatch helpers for pattern commands."""

from __future__ import annotations

from src.events.commands import AddPatternCommand, EditPatternCommand, RemovePatternCommand, SetPatternEnabledCommand
from src.events.pattern_scopes import ChannelScopeMode, OfflineScope, SubscriptionScope, UserScopeMode
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_add_pattern(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_text: str,
    is_regex: bool,
    channel_scope_mode: ChannelScopeMode,
    twitch_channel_logins: tuple[str, ...],
    user_scope_mode: UserScopeMode,
    twitch_user_logins: tuple[str, ...],
    sub_state: SubscriptionScope,
    offline_state: OfflineScope,
    case_sensitive: bool,
    color: str | None,
    disabled: bool,
    priority: int | None,
) -> object:
    return await services.pattern.handle_add_command(
        AddPatternCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_text=pattern_text,
            is_regex=is_regex,
            channel_scope_mode=channel_scope_mode,
            twitch_channel_logins=twitch_channel_logins,
            user_scope_mode=user_scope_mode,
            twitch_user_logins=twitch_user_logins,
            sub_state=sub_state,
            offline_state=offline_state,
            case_sensitive=case_sensitive,
            color=color,
            disabled=disabled,
            priority=priority,
        ),
    )


async def dispatch_remove_pattern(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> object:
    return await services.pattern.handle_remove_command(
        RemovePatternCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
        ),
    )


async def dispatch_enable_pattern(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> object:
    return await services.pattern.handle_set_enabled_command(
        SetPatternEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
            enabled=True,
        ),
    )


async def dispatch_disable_pattern(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
) -> object:
    return await services.pattern.handle_set_enabled_command(
        SetPatternEnabledCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
            enabled=False,
        ),
    )


async def dispatch_edit_pattern(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
    pattern_text: str | None,
    is_regex: bool | None,
    channel_scope_mode: ChannelScopeMode | None,
    twitch_channel_logins: tuple[str, ...] | None,
    user_scope_mode: UserScopeMode | None,
    twitch_user_logins: tuple[str, ...] | None,
    sub_state: SubscriptionScope | None,
    offline_state: OfflineScope | None,
    case_sensitive: bool | None,
    color: str | None,
    clear_color: bool,
    priority: int | None,
) -> object:
    return await services.pattern.handle_edit_command(
        EditPatternCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
            pattern_text=pattern_text,
            is_regex=is_regex,
            channel_scope_mode=channel_scope_mode,
            twitch_channel_logins=twitch_channel_logins,
            user_scope_mode=user_scope_mode,
            twitch_user_logins=twitch_user_logins,
            sub_state=sub_state,
            offline_state=offline_state,
            case_sensitive=case_sensitive,
            color=color,
            clear_color=clear_color,
            priority=priority,
        ),
    )
