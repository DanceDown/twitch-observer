"""Split reply command operations by responsibility."""

from __future__ import annotations

from src.discord_results import build_thread_result
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
)

from .command_support import ReplyCommandSupport


async def handle_pattern_action(
    *,
    command,
    action: str,
    thread,
    pattern_repository,
    reply_repository,
    account_repository,
    localizer,
    support: ReplyCommandSupport,
) -> DiscordCommandResult:
    pattern = await pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
    if pattern is None:
        return build_thread_result(
            localizer,
            "results.reply.pattern_not_found",
            thread=thread,
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    display_id = await support.display_index(thread.thread_id, pattern.pattern_id) or pattern.pattern_id
    if action == "add":
        linked_account = await account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
        if linked_account is None:
            return build_thread_result(
                localizer,
                "results.reply.no_linked_account",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        message = command.message.strip()
        if not message:
            raise ValueError(support.text("results.reply.pattern_add_empty_message", language=thread.language))
        if len(message) > 500:
            raise ValueError(support.text("results.reply.pattern_add_message_too_long", language=thread.language))
        existing_reply = await reply_repository.get_by_pattern(thread_id=thread.thread_id, pattern_id=pattern.pattern_id)
        if existing_reply is not None:
            return build_thread_result(
                localizer,
                "results.reply.already_exists",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        created = await reply_repository.add_reply(
            thread_id=thread.thread_id,
            pattern_id=pattern.pattern_id,
            reply_message=message,
            reply_as_reply=command.reply_as_reply,
        )
        if created is None:
            raise LookupError("Reply repository returned no row for add_reply.")
        return build_thread_result(
            localizer,
            "results.reply.added_pattern",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    "user_id": command.requester_id,
                    "id": display_id,
                    "mode": support.text(
                        "results.reply.added_pattern.mode.reply" if created.reply_as_reply else "results.reply.added_pattern.mode.message",
                        language=thread.language,
                    ),
                    "message": created.reply_message,
                }
            },
        )

    existing_reply = await reply_repository.get_by_pattern(thread_id=thread.thread_id, pattern_id=pattern.pattern_id)
    if existing_reply is None:
        return build_thread_result(
            localizer,
            "results.reply.none_configured",
            thread=thread,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    if action == "remove":
        cleared = await reply_repository.remove_reply(thread_id=thread.thread_id, pattern_id=pattern.pattern_id)
        if cleared is None:
            raise LookupError("Reply repository returned no row for remove_reply.")
        return build_thread_result(
            localizer,
            "results.reply.removed_pattern",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    "user_id": command.requester_id,
                    "id": display_id,
                    "message": existing_reply.reply_message,
                }
            },
        )

    if action == "disable":
        if existing_reply.disabled:
            return build_thread_result(
                localizer,
                "results.reply.already_disabled",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        disabled_reply = await reply_repository.set_reply_disabled(
            thread_id=thread.thread_id,
            pattern_id=pattern.pattern_id,
            disabled=True,
        )
        if disabled_reply is None:
            raise LookupError("Reply repository returned no row for disable pattern reply.")
        return build_thread_result(
            localizer,
            "results.reply.disabled_pattern",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    "user_id": command.requester_id,
                    "id": display_id,
                    "message": disabled_reply.reply_message,
                }
            },
        )

    if action == "enable":
        if not existing_reply.disabled:
            return build_thread_result(
                localizer,
                "results.reply.already_enabled",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        enabled_reply = await reply_repository.set_reply_disabled(
            thread_id=thread.thread_id,
            pattern_id=pattern.pattern_id,
            disabled=False,
        )
        if enabled_reply is None:
            raise LookupError("Reply repository returned no row for enable pattern reply.")
        return build_thread_result(
            localizer,
            "results.reply.enabled_pattern",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    "user_id": command.requester_id,
                    "id": display_id,
                    "message": enabled_reply.reply_message,
                }
            },
        )

    raise ValueError(support.text("results.reply.pattern_action_unsupported", language=thread.language))


async def handle_event_action(
    *,
    command,
    action: str,
    thread,
    event_configuration,
    account_repository,
    localizer,
    support: ReplyCommandSupport,
) -> DiscordCommandResult:
    if event_configuration is None:
        raise ValueError(support.text("results.reply.event_unavailable", language=thread.language))

    adapter_event = next(
        (
            item
            for item in await event_configuration.adapter_event_repository.list_events_for_thread(
                thread.thread_id,
                include_disabled=True,
            )
            if item.event_id == command.adapter_event_id
        ),
        None,
    )
    if adapter_event is None:
        return build_thread_result(
            localizer,
            "results.reply.event_not_found",
            thread=thread,
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    state_label = STREAM_EVENT_KEY_TO_STATE.get(adapter_event.event_key)
    if adapter_event.adapter_key != TWITCH_ADAPTER_KEY or adapter_event.subject_type != CHANNEL_SUBJECT_TYPE or state_label is None:
        raise ValueError(support.text("results.reply.unsupported_event", language=thread.language))

    cached = event_configuration.twitch_api.get_cached_user_by_id(adapter_event.subject_id.strip())
    twitch_channel = cached if cached is not None else await event_configuration.twitch_api.get_channel_by_id(adapter_event.subject_id)
    channel_display_name = twitch_channel.display_name
    channel_login = twitch_channel.login

    existing_reply = await event_configuration.adapter_event_action_repository.get_action(
        event_id=adapter_event.event_id,
        action_type=TWITCH_SEND_MESSAGE_ACTION,
    )

    if action == "add":
        linked_account = await account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
        if linked_account is None:
            return build_thread_result(
                localizer,
                "results.reply.no_linked_account",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        message = command.message.strip()
        if not message:
            raise ValueError(support.text("results.reply.event_add_empty_message", language=thread.language))
        if len(message) > 500:
            raise ValueError(support.text("results.reply.event_add_message_too_long", language=thread.language))
        created = await event_configuration.adapter_event_action_repository.upsert_action(
            event_id=adapter_event.event_id,
            action_type=TWITCH_SEND_MESSAGE_ACTION,
            message_template=message,
            reply_as_reply=False,
        )
        return build_thread_result(
            localizer,
            "results.reply.added_event",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    "user_id": command.requester_id,
                    "display_name": channel_display_name,
                    "login": channel_login,
                    "state": state_label,
                    "message": created.message_template or "",
                }
            },
        )

    if existing_reply is None:
        return build_thread_result(
            localizer,
            "results.reply.none_configured_event",
            thread=thread,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    if action == "remove":
        removed = await event_configuration.adapter_event_action_repository.remove_action(
            event_id=adapter_event.event_id,
            action_type=TWITCH_SEND_MESSAGE_ACTION,
        )
        if removed is None:
            raise LookupError("Reply repository returned no row for remove adapter-event action.")
        return build_thread_result(
            localizer,
            "results.reply.removed_event",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    "user_id": command.requester_id,
                    "display_name": channel_display_name,
                    "login": channel_login,
                    "state": state_label,
                    "message": existing_reply.message_template or "",
                }
            },
        )

    if action == "disable":
        if existing_reply.disabled:
            return build_thread_result(
                localizer,
                "results.reply.already_disabled",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        disabled_reply = await event_configuration.adapter_event_action_repository.set_action_disabled(
            event_id=adapter_event.event_id,
            action_type=TWITCH_SEND_MESSAGE_ACTION,
            disabled=True,
        )
        if disabled_reply is None:
            raise LookupError("Reply repository returned no row for disable adapter-event action.")
        return build_thread_result(
            localizer,
            "results.reply.disabled_event",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    "user_id": command.requester_id,
                    "display_name": channel_display_name,
                    "login": channel_login,
                    "state": state_label,
                    "message": disabled_reply.message_template or "",
                }
            },
        )

    if action == "enable":
        if not existing_reply.disabled:
            return build_thread_result(
                localizer,
                "results.reply.already_enabled",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        enabled_reply = await event_configuration.adapter_event_action_repository.set_action_disabled(
            event_id=adapter_event.event_id,
            action_type=TWITCH_SEND_MESSAGE_ACTION,
            disabled=False,
        )
        if enabled_reply is None:
            raise LookupError("Reply repository returned no row for enable adapter-event action.")
        return build_thread_result(
            localizer,
            "results.reply.enabled_event",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    "user_id": command.requester_id,
                    "display_name": channel_display_name,
                    "login": channel_login,
                    "state": state_label,
                    "message": enabled_reply.message_template or "",
                }
            },
        )

    raise ValueError(support.text("results.reply.event_action_unsupported", language=thread.language))
