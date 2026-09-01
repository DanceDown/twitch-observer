"""Reply command operations split into small, testable action handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    AdapterEventRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    TwitchAccountRecord,
    TwitchAccountRepository,
)
from src.discord_results import build_thread_result
from src.errors import ApplicationInvariantError
from src.events.commands import (
    AddChannelEventReplyCommand,
    AddPatternReplyCommand,
    RemoveChannelEventReplyCommand,
    RemovePatternReplyCommand,
    SetChannelEventReplyEnabledCommand,
    SetPatternReplyEnabledCommand,
)
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.gateways.twitch_api import TwitchUser
from src.localization import Localizer
from src.services.twitch_gateways import TwitchChannelStateLookup
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
)

from .command_support import ReplyCommandSupport

TWITCH_CHAT_REPLY_MAX_LENGTH = 500

ReplyAction = Literal["add", "remove", "disable", "enable"]
PatternReplyCommand = AddPatternReplyCommand | RemovePatternReplyCommand | SetPatternReplyEnabledCommand
EventReplyCommand = AddChannelEventReplyCommand | RemoveChannelEventReplyCommand | SetChannelEventReplyEnabledCommand


def _reply_add_missing() -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row("Reply add")


def _reply_remove_missing() -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row("Reply remove")


def _reply_disable_missing() -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row("Reply disable")


def _reply_enable_missing() -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row("Reply enable")


def _event_reply_remove_missing() -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row("Adapter event reply remove")


def _event_reply_disable_missing() -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row("Adapter event reply disable")


def _event_reply_enable_missing() -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row("Adapter event reply enable")


class ReplyEventConfigurationLike(Protocol):
    """Subset of event dependencies needed by reply command operations."""

    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    twitch_api: TwitchChannelStateLookup


@dataclass(slots=True, frozen=True)
class PatternActionDependencies:
    """Shared infrastructure used by pattern reply action handlers."""

    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    account_repository: TwitchAccountRepository
    localizer: Localizer
    support: ReplyCommandSupport


@dataclass(slots=True, frozen=True)
class EventActionDependencies:
    """Shared infrastructure used by channel-event reply action handlers."""

    event_configuration: ReplyEventConfigurationLike | None
    account_repository: TwitchAccountRepository
    localizer: Localizer
    support: ReplyCommandSupport


@dataclass(slots=True, frozen=True)
class _PatternActionContext:
    command: PatternReplyCommand
    thread: ThreadRecord
    pattern: PatternRecord
    display_id: int
    dependencies: PatternActionDependencies


@dataclass(slots=True, frozen=True)
class _EventActionContext:
    command: EventReplyCommand
    thread: ThreadRecord
    adapter_event: AdapterEventRecord
    state_label: str
    channel_display_name: str
    channel_login: str
    dependencies: EventActionDependencies


PatternExistingHandler = Callable[[_PatternActionContext, ReplyRecord], Awaitable[DiscordCommandResult]]
EventExistingHandler = Callable[[_EventActionContext, AdapterEventActionRecord], Awaitable[DiscordCommandResult]]


async def handle_pattern_action(
    *,
    command: PatternReplyCommand,
    action: ReplyAction,
    thread: ThreadRecord,
    dependencies: PatternActionDependencies,
) -> DiscordCommandResult:
    """Handle add/remove/enable/disable for pattern-bound auto-replies."""
    pattern = await dependencies.pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
    if pattern is None:
        return _thread_result(dependencies.localizer, "results.reply.pattern_not_found", thread, DiscordResultStyle.ERROR)

    display_id = await dependencies.support.display_index(thread.thread_id, pattern.pattern_id) or pattern.pattern_id
    context = _PatternActionContext(
        command=command,
        thread=thread,
        pattern=pattern,
        display_id=display_id,
        dependencies=dependencies,
    )

    if action == "add":
        return await _add_pattern_reply(context)

    existing_reply = await dependencies.reply_repository.get_by_pattern(thread_id=thread.thread_id, pattern_id=pattern.pattern_id)
    if existing_reply is None:
        return _thread_result(dependencies.localizer, "results.reply.none_configured", thread, DiscordResultStyle.INFO)
    return await _pattern_existing_action_handler(action, support=dependencies.support, language=thread.language)(context, existing_reply)


async def handle_event_action(
    *,
    command: EventReplyCommand,
    action: ReplyAction,
    thread: ThreadRecord,
    dependencies: EventActionDependencies,
) -> DiscordCommandResult:
    """Handle add/remove/enable/disable for live/offline auto-replies."""
    context = await _load_event_action_context(
        command=command,
        thread=thread,
        dependencies=dependencies,
    )
    if isinstance(context, DiscordCommandResult):
        return context

    if action == "add":
        return await _add_event_reply(context)

    existing_reply = await _require_event_configuration(context).adapter_event_action_repository.get_action(
        event_id=context.adapter_event.event_id,
        action_type=TWITCH_SEND_MESSAGE_ACTION,
    )
    if existing_reply is None:
        return _thread_result(dependencies.localizer, "results.reply.none_configured_event", thread, DiscordResultStyle.INFO)
    return await _event_existing_action_handler(action, support=dependencies.support, language=thread.language)(context, existing_reply)


async def _add_pattern_reply(context: _PatternActionContext) -> DiscordCommandResult:
    command = context.command
    dependencies = context.dependencies
    linked_account = await _linked_account(dependencies.account_repository, context.thread.account_id)
    if linked_account is None:
        return _thread_result(dependencies.localizer, "results.reply.no_linked_account", context.thread, DiscordResultStyle.ERROR)

    message = _validated_reply_message(
        command.message,
        empty_key="results.reply.pattern_add_empty_message",
        too_long_key="results.reply.pattern_add_message_too_long",
        thread=context.thread,
        support=dependencies.support,
    )
    existing_reply = await dependencies.reply_repository.get_by_pattern(
        thread_id=context.thread.thread_id,
        pattern_id=context.pattern.pattern_id,
    )
    if existing_reply is not None:
        return _thread_result(dependencies.localizer, "results.reply.already_exists", context.thread, DiscordResultStyle.ERROR)

    created = await dependencies.reply_repository.add_reply(
        thread_id=context.thread.thread_id,
        pattern_id=context.pattern.pattern_id,
        reply_message=message,
        reply_as_reply=command.reply_as_reply,
    )
    if created is None:
        raise _reply_add_missing()
    return _pattern_result(context, "results.reply.added_pattern", created.reply_message, _pattern_reply_mode(context, created))


async def _remove_pattern_reply(context: _PatternActionContext, existing_reply: ReplyRecord) -> DiscordCommandResult:
    cleared = await context.dependencies.reply_repository.remove_reply(
        thread_id=context.thread.thread_id,
        pattern_id=context.pattern.pattern_id,
    )
    if cleared is None:
        raise _reply_remove_missing()
    return _pattern_result(context, "results.reply.removed_pattern", existing_reply.reply_message)


async def _disable_pattern_reply(context: _PatternActionContext, existing_reply: ReplyRecord) -> DiscordCommandResult:
    if existing_reply.disabled:
        return _thread_result(context.dependencies.localizer, "results.reply.already_disabled", context.thread, DiscordResultStyle.INFO)

    disabled_reply = await context.dependencies.reply_repository.set_reply_disabled(
        thread_id=context.thread.thread_id,
        pattern_id=context.pattern.pattern_id,
        disabled=True,
    )
    if disabled_reply is None:
        raise _reply_disable_missing()
    return _pattern_result(context, "results.reply.disabled_pattern", disabled_reply.reply_message)


async def _enable_pattern_reply(context: _PatternActionContext, existing_reply: ReplyRecord) -> DiscordCommandResult:
    if not existing_reply.disabled:
        return _thread_result(context.dependencies.localizer, "results.reply.already_enabled", context.thread, DiscordResultStyle.INFO)

    enabled_reply = await context.dependencies.reply_repository.set_reply_disabled(
        thread_id=context.thread.thread_id,
        pattern_id=context.pattern.pattern_id,
        disabled=False,
    )
    if enabled_reply is None:
        raise _reply_enable_missing()
    return _pattern_result(context, "results.reply.enabled_pattern", enabled_reply.reply_message)


async def _load_event_action_context(
    *,
    command: EventReplyCommand,
    thread: ThreadRecord,
    dependencies: EventActionDependencies,
) -> _EventActionContext | DiscordCommandResult:
    event_configuration = dependencies.event_configuration
    if event_configuration is None:
        raise ValueError(dependencies.support.text("results.reply.event_unavailable", language=thread.language))

    adapter_event = await _find_adapter_event(event_configuration.adapter_event_repository, thread.thread_id, command.adapter_event_id)
    if adapter_event is None:
        return _thread_result(dependencies.localizer, "results.reply.event_not_found", thread, DiscordResultStyle.ERROR)

    state_label = _supported_event_state_label(adapter_event, support=dependencies.support, language=thread.language)
    twitch_channel = await _event_twitch_channel(event_configuration.twitch_api, adapter_event)
    return _EventActionContext(
        command=command,
        thread=thread,
        adapter_event=adapter_event,
        state_label=state_label,
        channel_display_name=twitch_channel.display_name,
        channel_login=twitch_channel.login,
        dependencies=dependencies,
    )


async def _add_event_reply(context: _EventActionContext) -> DiscordCommandResult:
    command = context.command
    dependencies = context.dependencies
    event_configuration = _require_event_configuration(context)

    linked_account = await _linked_account(dependencies.account_repository, context.thread.account_id)
    if linked_account is None:
        return _thread_result(dependencies.localizer, "results.reply.no_linked_account", context.thread, DiscordResultStyle.ERROR)

    message = _validated_reply_message(
        command.message,
        empty_key="results.reply.event_add_empty_message",
        too_long_key="results.reply.event_add_message_too_long",
        thread=context.thread,
        support=dependencies.support,
    )
    created = await event_configuration.adapter_event_action_repository.upsert_action(
        event_id=context.adapter_event.event_id,
        action_type=TWITCH_SEND_MESSAGE_ACTION,
        message_template=message,
        reply_as_reply=False,
    )
    return _event_result(context, "results.reply.added_event", created.message_template or "")


async def _remove_event_reply(
    context: _EventActionContext,
    existing_reply: AdapterEventActionRecord,
) -> DiscordCommandResult:
    event_configuration = _require_event_configuration(context)
    removed = await event_configuration.adapter_event_action_repository.remove_action(
        event_id=context.adapter_event.event_id,
        action_type=TWITCH_SEND_MESSAGE_ACTION,
    )
    if removed is None:
        raise _event_reply_remove_missing()
    return _event_result(context, "results.reply.removed_event", existing_reply.message_template or "")


async def _disable_event_reply(
    context: _EventActionContext,
    existing_reply: AdapterEventActionRecord,
) -> DiscordCommandResult:
    if existing_reply.disabled:
        return _thread_result(context.dependencies.localizer, "results.reply.already_disabled", context.thread, DiscordResultStyle.INFO)

    event_configuration = _require_event_configuration(context)
    disabled_reply = await event_configuration.adapter_event_action_repository.set_action_disabled(
        event_id=context.adapter_event.event_id,
        action_type=TWITCH_SEND_MESSAGE_ACTION,
        disabled=True,
    )
    if disabled_reply is None:
        raise _event_reply_disable_missing()
    return _event_result(context, "results.reply.disabled_event", disabled_reply.message_template or "")


async def _enable_event_reply(
    context: _EventActionContext,
    existing_reply: AdapterEventActionRecord,
) -> DiscordCommandResult:
    if not existing_reply.disabled:
        return _thread_result(context.dependencies.localizer, "results.reply.already_enabled", context.thread, DiscordResultStyle.INFO)

    event_configuration = _require_event_configuration(context)
    enabled_reply = await event_configuration.adapter_event_action_repository.set_action_disabled(
        event_id=context.adapter_event.event_id,
        action_type=TWITCH_SEND_MESSAGE_ACTION,
        disabled=False,
    )
    if enabled_reply is None:
        raise _event_reply_enable_missing()
    return _event_result(context, "results.reply.enabled_event", enabled_reply.message_template or "")


def _pattern_existing_action_handler(
    action: ReplyAction,
    *,
    support: ReplyCommandSupport,
    language: str,
) -> PatternExistingHandler:
    handlers: dict[ReplyAction, PatternExistingHandler] = {
        "remove": _remove_pattern_reply,
        "disable": _disable_pattern_reply,
        "enable": _enable_pattern_reply,
    }
    if action in handlers:
        return handlers[action]
    raise ValueError(support.text("results.reply.pattern_action_unsupported", language=language))


def _event_existing_action_handler(
    action: ReplyAction,
    *,
    support: ReplyCommandSupport,
    language: str,
) -> EventExistingHandler:
    handlers: dict[ReplyAction, EventExistingHandler] = {
        "remove": _remove_event_reply,
        "disable": _disable_event_reply,
        "enable": _enable_event_reply,
    }
    if action in handlers:
        return handlers[action]
    raise ValueError(support.text("results.reply.event_action_unsupported", language=language))


async def _find_adapter_event(
    adapter_event_repository: AdapterEventRepository,
    thread_id: int,
    adapter_event_id: int,
) -> AdapterEventRecord | None:
    events = await adapter_event_repository.list_events_for_thread(thread_id, include_disabled=True)
    return next((item for item in events if item.event_id == adapter_event_id), None)


def _supported_event_state_label(
    adapter_event: AdapterEventRecord,
    *,
    support: ReplyCommandSupport,
    language: str,
) -> str:
    state_label = STREAM_EVENT_KEY_TO_STATE.get(adapter_event.event_key)
    if adapter_event.adapter_key == TWITCH_ADAPTER_KEY and adapter_event.subject_type == CHANNEL_SUBJECT_TYPE and state_label is not None:
        return state_label
    raise ValueError(support.text("results.reply.unsupported_event", language=language))


async def _event_twitch_channel(twitch_api: TwitchChannelStateLookup, adapter_event: AdapterEventRecord) -> TwitchUser:
    cached = twitch_api.get_cached_user_by_id(adapter_event.subject_id.strip())
    return cached if cached is not None else await twitch_api.get_channel_by_id(adapter_event.subject_id)


async def _linked_account(account_repository: TwitchAccountRepository, account_id: int | None) -> TwitchAccountRecord | None:
    return await account_repository.get_by_account_id(account_id) if account_id is not None else None


def _require_event_configuration(context: _EventActionContext) -> ReplyEventConfigurationLike:
    event_configuration = context.dependencies.event_configuration
    if event_configuration is not None:
        return event_configuration
    raise ValueError(context.dependencies.support.text("results.reply.event_unavailable", language=context.thread.language))


def _validated_reply_message(
    message: str,
    *,
    empty_key: str,
    too_long_key: str,
    thread: ThreadRecord,
    support: ReplyCommandSupport,
) -> str:
    normalized = message.strip()
    if not normalized:
        raise ValueError(support.text(empty_key, language=thread.language))
    if len(normalized) > TWITCH_CHAT_REPLY_MAX_LENGTH:
        raise ValueError(support.text(too_long_key, language=thread.language))
    return normalized


def _pattern_result(
    context: _PatternActionContext,
    key: str,
    message: str,
    mode: str | None = None,
) -> DiscordCommandResult:
    view: dict[str, object] = {
        "user_id": context.command.requester_id,
        "id": context.display_id,
        "message": message,
    }
    if mode is not None:
        view["mode"] = mode
    return build_thread_result(
        context.dependencies.localizer,
        key,
        thread=context.thread,
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
        sources={"view": view},
    )


def _event_result(
    context: _EventActionContext,
    key: str,
    message: str,
) -> DiscordCommandResult:
    return build_thread_result(
        context.dependencies.localizer,
        key,
        thread=context.thread,
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
        sources={
            "view": {
                "user_id": context.command.requester_id,
                "display_name": context.channel_display_name,
                "login": context.channel_login,
                "state": context.state_label,
                "message": message,
            }
        },
    )


def _thread_result(
    localizer: Localizer,
    key: str,
    thread: ThreadRecord,
    style: DiscordResultStyle,
) -> DiscordCommandResult:
    return build_thread_result(
        localizer,
        key,
        thread=thread,
        style=style,
        ephemeral=True,
    )


def _pattern_reply_mode(context: _PatternActionContext, reply: ReplyRecord) -> str:
    key = "results.reply.added_pattern.mode.reply" if reply.reply_as_reply else "results.reply.added_pattern.mode.message"
    return context.dependencies.support.text(key, language=context.thread.language)
