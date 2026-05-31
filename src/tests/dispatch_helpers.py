"""Test-only convenience wrappers around the explicit Discord dispatch functions."""

from __future__ import annotations

from types import SimpleNamespace

from src.entrypoints.discord.dispatch import (
    dispatch_add_channel_event,
    dispatch_add_channel_event_reply,
    dispatch_add_pattern,
    dispatch_add_pattern_reply,
    dispatch_add_tracked_channel,
    dispatch_clear_permissions,
    dispatch_disable_channel_event_reply,
    dispatch_disable_pattern,
    dispatch_disable_pattern_reply,
    dispatch_disable_thread,
    dispatch_edit_pattern,
    dispatch_enable_channel_event_reply,
    dispatch_enable_pattern,
    dispatch_enable_pattern_reply,
    dispatch_enable_thread,
    dispatch_grant_permissions,
    dispatch_join_thread,
    dispatch_leave_thread,
    dispatch_remove_channel_event,
    dispatch_remove_channel_event_reply,
    dispatch_remove_pattern,
    dispatch_remove_pattern_reply,
    dispatch_remove_tracked_channel,
    dispatch_revoke_permissions,
    dispatch_send_twitch_message,
    dispatch_set_channel_event_color,
    dispatch_set_thread_color,
    dispatch_set_thread_language,
    dispatch_set_tracked_channel_color,
    dispatch_show_configuration,
    dispatch_start_account_link,
    dispatch_ui_flow_decision,
    dispatch_unlink_account,
)
from src.events.event_types import ChannelScopeMode, OfflineScope, StreamEventKind, SubscriptionScope, UIFlowKind, UIFlowStep, UserScopeMode


def make_services(**services):
    return SimpleNamespace(**services)


async def dispatch_thread_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    color: str | None = None,
    clear_color: bool = False,
    language: str | None = None,
):
    if action == "join":
        return await dispatch_join_thread(services, discord_channel_id=discord_channel_id, requester_id=requester_id)
    if action == "leave":
        return await dispatch_leave_thread(services, discord_channel_id=discord_channel_id, requester_id=requester_id)
    if action == "enable":
        return await dispatch_enable_thread(services, discord_channel_id=discord_channel_id, requester_id=requester_id)
    if action == "disable":
        return await dispatch_disable_thread(services, discord_channel_id=discord_channel_id, requester_id=requester_id)
    if action == "color":
        return await dispatch_set_thread_color(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            color=None if clear_color else color,
        )
    if action == "language" and language is not None:
        return await dispatch_set_thread_language(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            language=language,
        )
    raise ValueError(f"Unsupported thread action `{action}`.")


async def dispatch_channel_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    twitch_channel_login: str,
    color: str | None = None,
    clear_color: bool = False,
):
    if action == "add":
        return await dispatch_add_tracked_channel(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
        )
    if action == "remove":
        return await dispatch_remove_tracked_channel(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
        )
    if action == "color":
        return await dispatch_set_tracked_channel_color(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
            color=None if clear_color else color,
        )
    raise ValueError(f"Unsupported channel action `{action}`.")


async def dispatch_pattern_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    pattern_text: str | None,
    pattern_id: int | None,
    is_regex: bool | None,
    channel_scope_mode: str,
    twitch_channel_logins: tuple[str, ...],
    user_scope_mode: str,
    twitch_user_logins: tuple[str, ...],
    sub_state: str,
    offline_state: str,
    case_sensitive: bool,
    color: str | None,
    disabled: bool,
    priority: int | None = None,
):
    if action == "add":
        return await dispatch_add_pattern(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_text=pattern_text or "",
            is_regex=bool(is_regex),
            channel_scope_mode=ChannelScopeMode(channel_scope_mode),
            twitch_channel_logins=twitch_channel_logins,
            user_scope_mode=UserScopeMode(user_scope_mode),
            twitch_user_logins=twitch_user_logins,
            sub_state=SubscriptionScope(sub_state),
            offline_state=OfflineScope(offline_state),
            case_sensitive=case_sensitive,
            color=color,
            disabled=disabled,
            priority=priority,
        )
    if action == "remove" and pattern_id is not None:
        return await dispatch_remove_pattern(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
        )
    if action == "disable" and pattern_id is not None:
        return await dispatch_disable_pattern(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
        )
    if action == "enable" and pattern_id is not None:
        return await dispatch_enable_pattern(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            pattern_id=pattern_id,
        )
    raise ValueError(f"Unsupported pattern action `{action}`.")


async def dispatch_pattern_edit_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    pattern_id: int,
    pattern_text: str | None,
    is_regex: bool | None,
    channel_scope_mode: str | None,
    twitch_channel_logins: tuple[str, ...] | None,
    user_scope_mode: str | None,
    twitch_user_logins: tuple[str, ...] | None,
    sub_state: str | None,
    offline_state: str | None,
    case_sensitive: bool | None,
    color: str | None,
    clear_color: bool,
    priority: int | None,
):
    return await dispatch_edit_pattern(
        services,
        discord_channel_id=discord_channel_id,
        requester_id=requester_id,
        pattern_id=pattern_id,
        pattern_text=pattern_text,
        is_regex=is_regex,
        channel_scope_mode=None if channel_scope_mode is None else ChannelScopeMode(channel_scope_mode),
        twitch_channel_logins=twitch_channel_logins,
        user_scope_mode=None if user_scope_mode is None else UserScopeMode(user_scope_mode),
        twitch_user_logins=twitch_user_logins,
        sub_state=None if sub_state is None else SubscriptionScope(sub_state),
        offline_state=None if offline_state is None else OfflineScope(offline_state),
        case_sensitive=case_sensitive,
        color=color,
        clear_color=clear_color,
        priority=priority,
    )


async def dispatch_show_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    sections: tuple[str, ...],
):
    return await dispatch_show_configuration(
        services,
        discord_channel_id=discord_channel_id,
        requester_id=requester_id,
        sections=sections,
    )


async def dispatch_permission_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    target_user_id: int,
    permissions: tuple[str, ...] | None,
):
    normalized_permissions = permissions or ()
    if action == "grant":
        return await dispatch_grant_permissions(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            target_user_id=target_user_id,
            permissions=normalized_permissions,
        )
    if action == "revoke":
        return await dispatch_revoke_permissions(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            target_user_id=target_user_id,
            permissions=normalized_permissions,
        )
    if action == "clear":
        return await dispatch_clear_permissions(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            target_user_id=target_user_id,
        )
    raise ValueError(f"Unsupported permission action `{action}`.")


async def dispatch_account_command(
    services,
    *,
    requester_id: int,
    discord_channel_id: int | None,
    action: str,
):
    if action == "link":
        return await dispatch_start_account_link(
            services,
            requester_id=requester_id,
            discord_channel_id=discord_channel_id,
        )
    if action == "unlink":
        return await dispatch_unlink_account(
            services,
            requester_id=requester_id,
            discord_channel_id=discord_channel_id,
        )
    raise ValueError(f"Unsupported account action `{action}`.")


async def dispatch_reply_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    pattern_id: int,
    message: str | None,
    reply_as_reply: bool,
    target_type: str = "pattern",
    adapter_event_id: int | None = None,
):
    if target_type == "pattern":
        if action == "add":
            return await dispatch_add_pattern_reply(
                services,
                discord_channel_id=discord_channel_id,
                requester_id=requester_id,
                pattern_id=pattern_id,
                message=message or "",
                reply_as_reply=reply_as_reply,
            )
        if action == "remove":
            return await dispatch_remove_pattern_reply(
                services,
                discord_channel_id=discord_channel_id,
                requester_id=requester_id,
                pattern_id=pattern_id,
            )
        if action == "disable":
            return await dispatch_disable_pattern_reply(
                services,
                discord_channel_id=discord_channel_id,
                requester_id=requester_id,
                pattern_id=pattern_id,
            )
        if action == "enable":
            return await dispatch_enable_pattern_reply(
                services,
                discord_channel_id=discord_channel_id,
                requester_id=requester_id,
                pattern_id=pattern_id,
            )
    if adapter_event_id is None:
        raise ValueError("Missing adapter_event_id for event-bound reply.")
    if action == "add":
        return await dispatch_add_channel_event_reply(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
            message=message or "",
            reply_as_reply=reply_as_reply,
        )
    if action == "remove":
        return await dispatch_remove_channel_event_reply(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
        )
    if action == "disable":
        return await dispatch_disable_channel_event_reply(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
        )
    if action == "enable":
        return await dispatch_enable_channel_event_reply(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            adapter_event_id=adapter_event_id,
        )
    raise ValueError(f"Unsupported reply action `{action}`.")


async def dispatch_channel_event_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str = "add",
    twitch_channel_id: str,
    event_key: str,
    color: str | None = None,
):
    event_kind = StreamEventKind(event_key)
    if action == "add":
        return await dispatch_add_channel_event(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_id=twitch_channel_id,
            event_kind=event_kind,
        )
    if action == "remove":
        return await dispatch_remove_channel_event(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_id=twitch_channel_id,
            event_kind=event_kind,
        )
    if action == "color":
        return await dispatch_set_channel_event_color(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_id=twitch_channel_id,
            event_kind=event_kind,
            color=color,
        )
    raise ValueError(f"Unsupported channel-event action `{action}`.")


async def dispatch_write_command(
    services,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_login: str,
    message: str,
    reply_parent_message_id: str | None,
):
    return await dispatch_send_twitch_message(
        services,
        discord_channel_id=discord_channel_id,
        requester_id=requester_id,
        twitch_channel_login=twitch_channel_login,
        message=message,
        reply_parent_message_id=reply_parent_message_id,
    )


async def dispatch_request_ui_flow_decision(
    services,
    *,
    discord_channel_id: int | None,
    requester_id: int,
    flow: str,
    step: str,
):
    return await dispatch_ui_flow_decision(
        services,
        discord_channel_id=discord_channel_id,
        requester_id=requester_id,
        flow=UIFlowKind(flow),
        step=UIFlowStep(step),
    )
