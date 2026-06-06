"""Split pattern command mutations by responsibility."""

from __future__ import annotations

import logging
import re

from src.database.connection import PatternRecord, ThreadRecord
from src.discord_results import build_thread_result, discord_user_mention
from src.events.event_types import AddPatternCommand, DiscordCommandResult, DiscordResultStyle, EditPatternCommand, SetPatternEnabledCommand

from .command_support import PatternCommandSupport

logger = logging.getLogger(__name__)


async def add_pattern(
    *,
    command: AddPatternCommand,
    thread: ThreadRecord,
    pattern_repository,
    localizer,
    support: PatternCommandSupport,
) -> DiscordCommandResult:
    logger.debug("Adding pattern request: %r", command)
    text = command.pattern_text.strip()
    if not text:
        raise ValueError(support.text(thread, "results.pattern.empty_pattern"))
    if command.color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", command.color.strip()):
        raise ValueError(support.text(thread, "results.pattern.invalid_color"))
    if command.is_regex:
        re.compile(text)
    if command.priority is not None and not 0 <= command.priority <= 9:
        raise ValueError(support.text(thread, "results.pattern.invalid_priority"))

    scoped_channels, scoped_users = await support.resolve_filters(
        channel_scope_mode=command.channel_scope_mode,
        twitch_channel_logins=command.twitch_channel_logins,
        user_scope_mode=command.user_scope_mode,
        twitch_user_logins=command.twitch_user_logins,
        thread=thread,
    )
    channel_scope_ids = tuple(channel.user_id for channel in scoped_channels)
    user_scope_ids = tuple(user.user_id for user in scoped_users)

    existing = await pattern_repository.find_exact_pattern(
        thread_id=thread.thread_id,
        regex=text,
        channel_scope_mode=command.channel_scope_mode.value,
        channel_scope_ids=channel_scope_ids,
        user_scope_mode=command.user_scope_mode.value,
        user_scope_ids=user_scope_ids,
        sub_state=command.sub_state.value,
        offline_state=command.offline_state.value,
        is_regex=command.is_regex,
        case_sensitive=command.case_sensitive,
    )
    if existing is not None:
        display_id = await support.display_index(thread.thread_id, existing.pattern_id) or existing.pattern_id
        return build_thread_result(
            localizer,
            "results.pattern.already_exists",
            thread=thread,
            ID=display_id,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    created = await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex=text,
        channel_scope_mode=command.channel_scope_mode.value,
        channel_scope_ids=channel_scope_ids,
        user_scope_mode=command.user_scope_mode.value,
        user_scope_ids=user_scope_ids,
        sub_state=command.sub_state.value,
        offline_state=command.offline_state.value,
        is_regex=command.is_regex,
        case_sensitive=command.case_sensitive,
        color=command.color.strip() if command.color else None,
        disabled=command.disabled,
        priority=(
            command.priority
            if command.priority is not None
            else support.default_priority_for(
                channel_scope_mode=command.channel_scope_mode,
                user_scope_mode=command.user_scope_mode,
                sub_state=command.sub_state,
                offline_state=command.offline_state,
            )
        ),
    )
    display_id = await support.display_index(thread.thread_id, created.pattern_id) or created.pattern_id
    logger.debug(
        "Added ping thread_id=%s pattern_id=%s regex=%r is_regex=%s channel_filter=%s user_filter=%s",
        thread.thread_id,
        created.pattern_id,
        created.regex,
        created.is_regex,
        created.channel_scope_ids,
        created.user_scope_ids,
    )
    return build_thread_result(
        localizer,
        "results.pattern.added_result",
        thread=thread,
        USER=discord_user_mention(localizer, command.requester_id, language=thread.language),
        ID=display_id,
        SUMMARY=support.format_pattern_summary(
            pattern=created,
            channel_logins=tuple(support.profile_item(channel.display_name, channel.login) for channel in scoped_channels),
            user_logins=tuple(support.profile_item(user.display_name, user.login) for user in scoped_users),
            language=thread.language,
            key_prefix="results.pattern.added_result.summary",
        ),
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )


async def remove_pattern(
    *,
    command,
    thread: ThreadRecord,
    pattern_repository,
    localizer,
    support: PatternCommandSupport,
) -> DiscordCommandResult:
    logger.debug("Removing pattern request: %r", command)
    pattern = await pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
    if pattern is None:
        return build_thread_result(
            localizer,
            "results.pattern.not_found_remove",
            thread=thread,
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    display_id = await support.display_index(thread.thread_id, pattern.pattern_id) or pattern.pattern_id
    await pattern_repository.remove_pattern(thread_id=pattern.thread_id, pattern_id=pattern.pattern_id)
    logger.debug("Removed pattern thread_id=%s pattern_id=%s regex=%r", pattern.thread_id, pattern.pattern_id, pattern.regex)
    return build_thread_result(
        localizer,
        "results.pattern.removed_result",
        thread=thread,
        USER=discord_user_mention(localizer, command.requester_id, language=thread.language),
        ID=display_id,
        TEXT=pattern.regex,
        PING_MODE=support.pattern_mode(pattern.is_regex, language=thread.language, scope="results.pattern.removed_result"),
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )


async def set_pattern_enabled(
    *,
    command: SetPatternEnabledCommand,
    thread: ThreadRecord,
    pattern_repository,
    localizer,
    support: PatternCommandSupport,
) -> DiscordCommandResult:
    action_prefix = "enable" if command.enabled else "disable"
    logger.debug("%s pattern request: %r", action_prefix.capitalize(), command)
    pattern = await pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
    if pattern is None:
        return build_thread_result(
            localizer,
            f"results.pattern.not_found_{action_prefix}",
            thread=thread,
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    if pattern.disabled == (not command.enabled):
        display_id = await support.display_index(thread.thread_id, pattern.pattern_id) or pattern.pattern_id
        return build_thread_result(
            localizer,
            f"results.pattern.already_{'enabled' if command.enabled else 'disabled'}",
            thread=thread,
            ID=display_id,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    updated = await pattern_repository.set_pattern_disabled(
        thread_id=pattern.thread_id,
        pattern_id=pattern.pattern_id,
        disabled=not command.enabled,
    )
    if updated is None:
        raise LookupError(f"Pattern repository returned no row for {action_prefix}.")

    display_id = await support.display_index(thread.thread_id, updated.pattern_id) or updated.pattern_id
    result_scope = "enabled_result" if command.enabled else "disabled_result"
    return build_thread_result(
        localizer,
        f"results.pattern.{result_scope}",
        thread=thread,
        USER=discord_user_mention(localizer, command.requester_id, language=thread.language),
        ID=display_id,
        TEXT=updated.regex,
        PING_MODE=support.pattern_mode(updated.is_regex, language=thread.language, scope=f"results.pattern.{result_scope}"),
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )


async def edit_pattern(
    *,
    command: EditPatternCommand,
    thread: ThreadRecord,
    pattern_repository,
    localizer,
    support: PatternCommandSupport,
) -> DiscordCommandResult:
    pattern = await pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
    if pattern is None:
        return build_thread_result(
            localizer,
            "results.pattern.not_found_id",
            thread=thread,
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    new_text = pattern.regex if command.pattern_text is None else command.pattern_text.strip()
    if not new_text:
        raise ValueError(support.text(thread, "results.pattern.empty_pattern"))

    new_is_regex = pattern.is_regex if command.is_regex is None else command.is_regex
    if new_is_regex:
        re.compile(new_text)

    new_channel_scope_mode = pattern.channel_scope_mode if command.channel_scope_mode is None else command.channel_scope_mode.value
    new_user_scope_mode = pattern.user_scope_mode if command.user_scope_mode is None else command.user_scope_mode.value
    new_sub_state = pattern.sub_state if command.sub_state is None else command.sub_state.value
    new_offline_state = pattern.offline_state if command.offline_state is None else command.offline_state.value
    new_case_sensitive = pattern.case_sensitive if command.case_sensitive is None else command.case_sensitive
    if command.clear_color:
        new_color = None
    elif command.color is None:
        new_color = pattern.color
    else:
        new_color = command.color.strip()
    if new_color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", new_color):
        raise ValueError(support.text(thread, "results.pattern.invalid_color"))
    new_priority = pattern.priority if command.priority is None else command.priority
    if not 0 <= new_priority <= 9:
        raise ValueError(support.text(thread, "results.pattern.invalid_priority"))

    scoped_channels, scoped_users = await support.resolve_pattern_edit_filters(
        channel_scope_mode=command.channel_scope_mode,
        twitch_channel_logins=command.twitch_channel_logins,
        user_scope_mode=command.user_scope_mode,
        twitch_user_logins=command.twitch_user_logins,
        thread=thread,
        pattern=pattern,
    )
    channel_scope_ids = tuple(channel.user_id for channel in scoped_channels)
    user_scope_ids = tuple(user.user_id for user in scoped_users)

    existing = await pattern_repository.find_exact_pattern(
        thread_id=thread.thread_id,
        regex=new_text,
        channel_scope_mode=new_channel_scope_mode,
        channel_scope_ids=channel_scope_ids,
        user_scope_mode=new_user_scope_mode,
        user_scope_ids=user_scope_ids,
        sub_state=new_sub_state,
        offline_state=new_offline_state,
        is_regex=new_is_regex,
        case_sensitive=new_case_sensitive,
    )
    if existing is not None and existing.pattern_id != pattern.pattern_id:
        display_id = await support.display_index(thread.thread_id, existing.pattern_id) or existing.pattern_id
        return build_thread_result(
            localizer,
            "results.pattern.already_exists_other",
            thread=thread,
            ID=display_id,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    updated = await pattern_repository.update_pattern(
        thread_id=thread.thread_id,
        pattern_id=pattern.pattern_id,
        regex=new_text,
        channel_scope_mode=new_channel_scope_mode,
        channel_scope_ids=channel_scope_ids,
        user_scope_mode=new_user_scope_mode,
        user_scope_ids=user_scope_ids,
        sub_state=new_sub_state,
        offline_state=new_offline_state,
        is_regex=new_is_regex,
        case_sensitive=new_case_sensitive,
        color=new_color,
        priority=new_priority,
    )
    if updated is None:
        raise LookupError("Pattern repository returned no row for update.")

    display_id = await support.display_index(thread.thread_id, updated.pattern_id) or updated.pattern_id
    old_channel_logins = await support.resolve_profile_items_from_ids(pattern.channel_scope_ids)
    old_user_logins = await support.resolve_profile_items_from_ids(pattern.user_scope_ids)
    return build_thread_result(
        localizer,
        "results.pattern.updated_result",
        thread=thread,
        USER=discord_user_mention(localizer, command.requester_id, language=thread.language),
        ID=display_id,
        SUMMARY=support.format_pattern_changes(
            before=pattern,
            after=updated,
            old_channel_logins=old_channel_logins,
            new_channel_logins=tuple(support.profile_item(channel.display_name, channel.login) for channel in scoped_channels),
            old_user_logins=old_user_logins,
            new_user_logins=tuple(support.profile_item(user.display_name, user.login) for user in scoped_users),
            language=thread.language,
            key_prefix="results.pattern.updated_result.summary",
        ),
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )
