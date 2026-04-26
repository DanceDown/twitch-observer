from __future__ import annotations

"""Event-bus dispatch helpers used by Discord slash commands and modals."""

import asyncio

from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordAccountRequestedEvent,
    DiscordChannelEventRequestedEvent,
    DiscordChannelRequestedEvent,
    DiscordCommandResult,
    DiscordPatternEditRequestedEvent,
    DiscordPatternRequestedEvent,
    DiscordPermissionRequestedEvent,
    DiscordReplyRequestedEvent,
    DiscordShowRequestedEvent,
    DiscordThreadRequestedEvent,
    DiscordUIFlowDecision,
    DiscordUIFlowRequestedEvent,
    DiscordUserRequestedEvent,
    DiscordWriteRequestedEvent,
    EventType,
)


async def dispatch_channel_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    twitch_channel_login: str,
    color: str | None = None,
    clear_color: bool = False,
) -> DiscordCommandResult:
    """Publish a channel add/remove request and await the service result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_CHANNEL_REQUESTED,
        DiscordChannelRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            action=action,
            twitch_channel_login=twitch_channel_login,
            color=color,
            clear_color=clear_color,
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_channel_event_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str = "add",
    twitch_channel_id: str,
    event_key: str,
) -> DiscordCommandResult:
    """Publish one tracked channel-event configuration request and await the result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_CHANNEL_EVENT_REQUESTED,
        DiscordChannelEventRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            action=action,
            twitch_channel_id=twitch_channel_id,
            event_key=event_key,
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_user_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    twitch_user_login: str,
) -> DiscordCommandResult:
    """Publish a tracked-user add/remove request and await the service result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_USER_REQUESTED,
        DiscordUserRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            action=action,
            twitch_user_login=twitch_user_login,
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_thread_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    color: str | None = None,
    clear_color: bool = False,
    language: str | None = None,
) -> DiscordCommandResult:
    """Publish a join/leave request for one Discord context and await the result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_THREAD_REQUESTED,
        DiscordThreadRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            action=action,
            color=color,
            clear_color=clear_color,
            language=language,
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_pattern_command(
    event_bus: EventBus,
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
) -> DiscordCommandResult:
    """Publish a ping or regex command request and await the service result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_PATTERN_REQUESTED,
        DiscordPatternRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            action=action,
            pattern_text=pattern_text,
            pattern_id=pattern_id,
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
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_show_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    sections: tuple[str, ...],
) -> DiscordCommandResult:
    """Publish a configuration overview request and await the rendered result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_SHOW_REQUESTED,
        DiscordShowRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            sections=sections,
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_pattern_edit_command(
    event_bus: EventBus,
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
) -> DiscordCommandResult:
    """Publish a pattern edit request and await the service result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_PATTERN_EDIT_REQUESTED,
        DiscordPatternEditRequestedEvent(
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
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_account_command(
    event_bus: EventBus,
    *,
    requester_id: int,
    discord_channel_id: int | None,
    action: str,
) -> DiscordCommandResult:
    """Publish an account link/unlink/show request and await the result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_ACCOUNT_REQUESTED,
        DiscordAccountRequestedEvent(
            requester_id=requester_id,
            discord_channel_id=discord_channel_id,
            action=action,
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_reply_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    pattern_id: int,
    message: str | None,
    reply_as_reply: bool,
    target_type: str = "pattern",
    adapter_event_id: int | None = None,
) -> DiscordCommandResult:
    """Publish a reply add/remove/disable/enable request and await the result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_REPLY_REQUESTED,
        DiscordReplyRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            action=action,
            pattern_id=pattern_id,
            message=message,
            reply_as_reply=reply_as_reply,
            result_future=result_future,
            target_type=target_type,
            adapter_event_id=adapter_event_id,
        ),
    )
    return await result_future


async def dispatch_permission_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    target_user_id: int,
    permissions: tuple[str, ...] | None,
) -> DiscordCommandResult:
    """Publish a permission-management request and await the service result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_PERMISSION_REQUESTED,
        DiscordPermissionRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            action=action,
            target_user_id=target_user_id,
            permissions=permissions,
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_write_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    twitch_channel_login: str,
    message: str,
    reply_parent_message_id: str | None,
) -> DiscordCommandResult:
    """Publish a manual Twitch send request and await the service result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_WRITE_REQUESTED,
        DiscordWriteRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            twitch_channel_login=twitch_channel_login,
            message=message,
            reply_parent_message_id=reply_parent_message_id,
            result_future=result_future,
        ),
    )
    return await result_future


async def dispatch_ui_flow_decision(
    event_bus: EventBus,
    *,
    discord_channel_id: int | None,
    requester_id: int,
    flow: str,
    step: str,
) -> DiscordUIFlowDecision:
    """Ask services whether a Discord UI step may be rendered."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordUIFlowDecision] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_UI_FLOW_REQUESTED,
        DiscordUIFlowRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            flow=flow,
            step=step,
            result_future=result_future,
        ),
    )
    return await result_future
