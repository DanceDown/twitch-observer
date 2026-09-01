"""Split pattern command mutations by responsibility."""

from __future__ import annotations

import logging
import re

from src.database.connection import PatternCreate, PatternDefinition, PatternExactQuery, PatternRepository, PatternUpdate, ThreadRecord
from src.discord_results import build_thread_result
from src.errors import ApplicationInvariantError
from src.events.commands import AddPatternCommand, EditPatternCommand, RemovePatternCommand, SetPatternEnabledCommand
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer

from .command_support import PatternChangeRenderRequest, PatternCommandSupport
from .filters import PatternEditFilterRequest

logger = logging.getLogger(__name__)

PATTERN_PRIORITY_MIN = 0
PATTERN_PRIORITY_MAX = 9


def _pattern_toggle_missing(action_prefix: str) -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row(f"Pattern {action_prefix}")


def _pattern_update_missing() -> ApplicationInvariantError:
    return ApplicationInvariantError.operation_returned_no_row("Pattern update")


async def add_pattern(
    *,
    command: AddPatternCommand,
    thread: ThreadRecord,
    pattern_repository: PatternRepository,
    localizer: Localizer,
    support: PatternCommandSupport,
) -> DiscordCommandResult:
    """Create a validated pattern and return its Discord result."""
    logger.debug("Adding pattern request: %r", command)
    text = command.pattern_text.strip()
    if not text:
        raise ValueError(support.text(thread, "results.pattern.empty_pattern"))
    if command.color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", command.color.strip()):
        raise ValueError(support.text(thread, "results.pattern.invalid_color"))
    if command.is_regex:
        re.compile(text)
    if command.priority is not None and not PATTERN_PRIORITY_MIN <= command.priority <= PATTERN_PRIORITY_MAX:
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

    definition = PatternDefinition(
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
    existing = await pattern_repository.find_exact_pattern(
        PatternExactQuery(
            thread_id=thread.thread_id,
            definition=definition,
        )
    )
    if existing is not None:
        display_id = await support.display_index(thread.thread_id, existing.pattern_id) or existing.pattern_id
        return build_thread_result(
            localizer,
            "results.pattern.already_exists",
            thread=thread,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
            sources={"view": {"id": display_id}},
        )

    created = await pattern_repository.add_pattern(
        PatternCreate(
            thread_id=thread.thread_id,
            definition=definition,
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
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
        sources={
            "view": {
                "user_id": command.requester_id,
                "id": display_id,
                "summary": support.format_pattern_summary(
                    pattern=created,
                    channel_logins=tuple(support.profile_item(channel.display_name, channel.login) for channel in scoped_channels),
                    user_logins=tuple(support.profile_item(user.display_name, user.login) for user in scoped_users),
                    language=thread.language,
                    key_prefix="results.pattern.added_result.summary",
                ),
            }
        },
    )


async def remove_pattern(
    *,
    command: RemovePatternCommand,
    thread: ThreadRecord,
    pattern_repository: PatternRepository,
    localizer: Localizer,
    support: PatternCommandSupport,
) -> DiscordCommandResult:
    """Remove an existing pattern and return its Discord result."""
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
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
        sources={
            "view": {
                "user_id": command.requester_id,
                "id": display_id,
                "text": pattern.regex,
                "ping_mode": support.pattern_mode(
                    is_regex=pattern.is_regex,
                    language=thread.language,
                    scope="results.pattern.removed_result",
                ),
            }
        },
    )


async def set_pattern_enabled(
    *,
    command: SetPatternEnabledCommand,
    thread: ThreadRecord,
    pattern_repository: PatternRepository,
    localizer: Localizer,
    support: PatternCommandSupport,
) -> DiscordCommandResult:
    """Toggle an existing pattern and return its Discord result."""
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
            style=DiscordResultStyle.INFO,
            ephemeral=True,
            sources={"view": {"id": display_id}},
        )

    updated = await pattern_repository.set_pattern_disabled(
        thread_id=pattern.thread_id,
        pattern_id=pattern.pattern_id,
        disabled=not command.enabled,
    )
    if updated is None:
        raise _pattern_toggle_missing(action_prefix)

    display_id = await support.display_index(thread.thread_id, updated.pattern_id) or updated.pattern_id
    result_scope = "enabled_result" if command.enabled else "disabled_result"
    return build_thread_result(
        localizer,
        f"results.pattern.{result_scope}",
        thread=thread,
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
        sources={
            "view": {
                "user_id": command.requester_id,
                "id": display_id,
                "text": updated.regex,
                "ping_mode": support.pattern_mode(
                    is_regex=updated.is_regex,
                    language=thread.language,
                    scope=f"results.pattern.{result_scope}",
                ),
            }
        },
    )


async def edit_pattern(
    *,
    command: EditPatternCommand,
    thread: ThreadRecord,
    pattern_repository: PatternRepository,
    localizer: Localizer,
    support: PatternCommandSupport,
) -> DiscordCommandResult:
    """Apply validated sparse edits to an existing pattern."""
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
    if not PATTERN_PRIORITY_MIN <= new_priority <= PATTERN_PRIORITY_MAX:
        raise ValueError(support.text(thread, "results.pattern.invalid_priority"))

    scoped_channels, scoped_users = await support.resolve_pattern_edit_filters(
        PatternEditFilterRequest(
            channel_scope_mode=command.channel_scope_mode,
            twitch_channel_logins=command.twitch_channel_logins,
            user_scope_mode=command.user_scope_mode,
            twitch_user_logins=command.twitch_user_logins,
            thread=thread,
            pattern=pattern,
        )
    )
    channel_scope_ids = tuple(channel.user_id for channel in scoped_channels)
    user_scope_ids = tuple(user.user_id for user in scoped_users)

    definition = PatternDefinition(
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
    existing = await pattern_repository.find_exact_pattern(
        PatternExactQuery(
            thread_id=thread.thread_id,
            definition=definition,
        )
    )
    if existing is not None and existing.pattern_id != pattern.pattern_id:
        display_id = await support.display_index(thread.thread_id, existing.pattern_id) or existing.pattern_id
        return build_thread_result(
            localizer,
            "results.pattern.already_exists_other",
            thread=thread,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
            sources={"view": {"id": display_id}},
        )

    updated = await pattern_repository.update_pattern(
        PatternUpdate(
            thread_id=thread.thread_id,
            pattern_id=pattern.pattern_id,
            definition=definition,
            color=new_color,
            priority=new_priority,
        )
    )
    if updated is None:
        raise _pattern_update_missing()

    display_id = await support.display_index(thread.thread_id, updated.pattern_id) or updated.pattern_id
    old_channel_logins = await support.resolve_profile_items_from_ids(pattern.channel_scope_ids)
    old_user_logins = await support.resolve_profile_items_from_ids(pattern.user_scope_ids)
    return build_thread_result(
        localizer,
        "results.pattern.updated_result",
        thread=thread,
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
        sources={
            "view": {
                "user_id": command.requester_id,
                "id": display_id,
                "summary": support.format_pattern_changes(
                    PatternChangeRenderRequest(
                        before=pattern,
                        after=updated,
                        old_channel_logins=old_channel_logins,
                        new_channel_logins=tuple(support.profile_item(channel.display_name, channel.login) for channel in scoped_channels),
                        old_user_logins=old_user_logins,
                        new_user_logins=tuple(support.profile_item(user.display_name, user.login) for user in scoped_users),
                        language=thread.language,
                        key_prefix="results.pattern.updated_result.summary",
                    )
                ),
            }
        },
    )
