from __future__ import annotations

"""Business logic for `/ping` add/edit/remove requests."""

import logging
import re
from dataclasses import dataclass, field

from src.adapters.twitch_api import (
    TwitchAPIClient,
    TwitchAPIConfigurationError,
    TwitchAPIError,
    TwitchChannelNotFoundError,
)
from src.database.connection import (
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordPatternEditRequestedEvent,
    DiscordPatternRequestedEvent,
    DiscordResultStyle,
    EventType,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.services.patterns.filters import PatternFilterResolver
from src.services.patterns.presentation import PatternCommandPresenter
from src.utils.discord_embeds import escape_discord_text
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PatternCommandService:
    """Handle `/ping` add/edit/remove requests from Discord."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchAPIClient
    tracked_user_repository: TrackedUserRepository | None = None
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    def __post_init__(self) -> None:
        """Subscribe the service to incoming Discord pattern command events."""
        self.event_bus.subscribe(EventType.DISCORD_PATTERN_REQUESTED, self.handle_request)
        self.event_bus.subscribe(
            EventType.DISCORD_PATTERN_EDIT_REQUESTED,
            self.handle_edit_request,
        )

    async def handle_request(self, event: DiscordPatternRequestedEvent) -> None:
        """Handle one add/remove request and complete the command result future."""
        try:
            result = await self._handle_action(event)
        except (
            TwitchAPIConfigurationError,
            TwitchChannelNotFoundError,
            ValueError,
        ) as error:
            result = self._event_result(
                event,
                "results.validation_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except TwitchAPIError as error:
            result = self._event_result(
                event,
                "results.twitch_api_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except re.error as error:
            result = self._event_result(
                event,
                "results.regex_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling pattern command.")
            result = self._event_result(
                event,
                "results.unexpected_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def handle_edit_request(self, event: DiscordPatternEditRequestedEvent) -> None:
        """Handle one edit request and complete the command result future."""
        try:
            result = await self._edit_pattern(event)
        except (
            TwitchAPIConfigurationError,
            TwitchChannelNotFoundError,
            ValueError,
        ) as error:
            result = self._event_result(
                event,
                "results.validation_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except TwitchAPIError as error:
            result = self._event_result(
                event,
                "results.twitch_api_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except re.error as error:
            result = self._event_result(
                event,
                "results.regex_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling pattern edit command.")
            result = self._event_result(
                event,
                "results.unexpected_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_action(
        self,
        event: DiscordPatternRequestedEvent,
    ) -> DiscordCommandResult:
        if event.action in {"add", "remove"}:
            required_permission = ObserverPermission.MANAGE_PATTERNS
            denial_key = "results.pattern.manage_permission_denied"
        elif event.action in {"disable", "enable"}:
            required_permission = ObserverPermission.TOGGLE_PATTERNS
            denial_key = "results.pattern.toggle_permission_denied"
        else:
            required_permission = ObserverPermission.MANAGE_PATTERNS
            denial_key = "results.pattern.change_permission_denied"

        thread = self._ensure_pattern_permission(
            event.discord_channel_id,
            event.requester_id,
            required_permission=required_permission,
            denial_key=denial_key,
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        if event.action == "add":
            return await self._add_pattern(event, thread)
        if event.action == "remove":
            return await self._remove_pattern(event, thread)
        if event.action == "disable":
            return await self._disable_pattern(event, thread)
        if event.action == "enable":
            return await self._enable_pattern(event, thread)
        raise ValueError(self._text(None, "results.pattern.unsupported_action"))

    def _ensure_pattern_permission(
        self,
        discord_channel_id: int,
        requester_id: int,
        *,
        required_permission: ObserverPermission,
        denial_key: str,
    ) -> ThreadRecord | DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(discord_channel_id)
        if thread is None:
            return self.localizer.result(
                "results.not_joined",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=requester_id,
            permission_repository=self.permission_repository,
            required_permission=required_permission,
        ):
            return self.localizer.thread_result(
                denial_key,
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    async def _add_pattern(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        """Validate and persist a new ping or regex rule."""
        logger.debug("Adding pattern request: %r", event)
        text = (event.pattern_text or "").strip()
        if not text:
            raise ValueError(self._text(thread, "results.pattern.empty_pattern"))
        if event.is_regex is None:
            raise ValueError(self._text(thread, "results.pattern.missing_mode"))
        if event.color is not None and not re.fullmatch(
            r"#[0-9A-Fa-f]{6}",
            event.color.strip(),
        ):
            raise ValueError(self._text(thread, "results.pattern.invalid_color"))
        if event.is_regex:
            re.compile(text)
        if event.priority is not None and not 0 <= event.priority <= 9:
            raise ValueError(self._text(thread, "results.pattern.invalid_priority"))

        scoped_channels, scoped_users = await self._filter_resolver().resolve_filters(event, thread)

        existing = self.pattern_repository.find_exact_pattern(
            thread_id=thread.thread_id,
            regex=text,
            channel_scope_mode=event.channel_scope_mode,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=event.user_scope_mode,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=event.sub_state,
            offline_state=event.offline_state,
            is_regex=event.is_regex,
            case_sensitive=event.case_sensitive,
        )
        if existing is not None:
            return self.localizer.thread_result(
                "results.pattern.already_exists",
                thread=thread,
                TYPE=self._pattern_type(event.is_regex, language=thread.language),
                ID=existing.p_index,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        created = self.pattern_repository.add_pattern(
            thread_id=thread.thread_id,
            regex=text,
            channel_scope_mode=event.channel_scope_mode,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=event.user_scope_mode,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=event.sub_state,
            offline_state=event.offline_state,
            is_regex=event.is_regex,
            case_sensitive=event.case_sensitive,
            color=event.color.strip() if event.color else None,
            disabled=event.disabled,
            priority=(
                event.priority
                if event.priority is not None
                else self._default_priority_for(
                    channel_scope_mode=event.channel_scope_mode,
                    user_scope_mode=event.user_scope_mode,
                    sub_state=event.sub_state,
                    offline_state=event.offline_state,
                )
            ),
        )
        mode_name = self._pattern_type(event.is_regex, language=thread.language)
        logger.debug(
            "Added %s pattern thread_id=%s pattern_id=%s regex=%r channel_filter=%s user_filter=%s",
            mode_name,
            thread.thread_id,
            created.p_index,
            created.regex,
            created.channel_scope_ids,
            created.user_scope_ids,
        )
        return DiscordCommandResult(
            title=self.localizer.text(
                "results.pattern.added_title",
                language=thread.language,
                TYPE=mode_name,
            ),
            message=self._presenter().format_pattern_summary(
                action=self.localizer.text("results.pattern.actions.added", language=thread.language),
                pattern=created,
                channel_logins=tuple(channel.display_name for channel in scoped_channels),
                user_logins=tuple(user.display_name for user in scoped_users),
                language=thread.language,
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _remove_pattern(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        """Remove a pattern either by ID or by its full identifying fields."""
        logger.debug("Removing pattern request: %r", event)
        pattern = await self._locate_pattern_for_removal(event, thread)
        if pattern is None:
            return self.localizer.thread_result(
                "results.pattern.not_found_remove",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        self.pattern_repository.remove_pattern(
            thread_id=pattern.thread_id,
            p_index=pattern.p_index,
        )
        logger.debug(
            "Removed pattern thread_id=%s pattern_id=%s regex=%r",
            pattern.thread_id,
            pattern.p_index,
            pattern.regex,
        )
        mode_name = self._pattern_type(pattern.is_regex, language=thread.language)
        return DiscordCommandResult(
            title=self.localizer.text(
                "results.pattern.removed_title",
                language=thread.language,
                TYPE=mode_name,
            ),
            message=self.localizer.text(
                "results.pattern.removed",
                language=thread.language,
                TYPE=self._pattern_type(pattern.is_regex, language=thread.language),
                ID=pattern.p_index,
                TEXT=escape_discord_text(pattern.regex),
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _disable_pattern(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        """Disable an existing ping or regex rule without deleting it."""
        logger.debug("Disabling pattern request: %r", event)
        pattern = await self._locate_pattern_for_removal(event, thread)
        if pattern is None:
            return self.localizer.thread_result(
                "results.pattern.not_found_disable",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if pattern.disabled:
            return self.localizer.thread_result(
                "results.pattern.already_disabled",
                thread=thread,
                TYPE=self._pattern_type(pattern.is_regex, language=thread.language),
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.pattern_repository.set_pattern_disabled(
            thread_id=pattern.thread_id,
            p_index=pattern.p_index,
            disabled=True,
        )
        assert updated is not None
        mode_name = self._pattern_type(pattern.is_regex, language=thread.language)
        return DiscordCommandResult(
            title=self.localizer.text(
                "results.pattern.disabled_title",
                language=thread.language,
                TYPE=mode_name,
            ),
            message=self.localizer.text(
                "results.pattern.disabled",
                language=thread.language,
                TYPE=self._pattern_type(updated.is_regex, language=thread.language),
                ID=updated.p_index,
                TEXT=escape_discord_text(updated.regex),
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _enable_pattern(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        """Enable an existing ping or regex rule without recreating it."""
        logger.debug("Enabling pattern request: %r", event)
        pattern = await self._locate_pattern_for_removal(event, thread)
        if pattern is None:
            return self.localizer.thread_result(
                "results.pattern.not_found_enable",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not pattern.disabled:
            return self.localizer.thread_result(
                "results.pattern.already_enabled",
                thread=thread,
                TYPE=self._pattern_type(pattern.is_regex, language=thread.language),
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.pattern_repository.set_pattern_disabled(
            thread_id=pattern.thread_id,
            p_index=pattern.p_index,
            disabled=False,
        )
        assert updated is not None
        mode_name = self._pattern_type(pattern.is_regex, language=thread.language)
        return DiscordCommandResult(
            title=self.localizer.text(
                "results.pattern.enabled_title",
                language=thread.language,
                TYPE=mode_name,
            ),
            message=self.localizer.text(
                "results.pattern.enabled",
                language=thread.language,
                TYPE=self._pattern_type(updated.is_regex, language=thread.language),
                ID=updated.p_index,
                TEXT=escape_discord_text(updated.regex),
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _edit_pattern(
        self,
        event: DiscordPatternEditRequestedEvent,
    ) -> DiscordCommandResult:
        thread = self._ensure_pattern_permission(
            event.discord_channel_id,
            event.requester_id,
            required_permission=ObserverPermission.MANAGE_PATTERNS,
            denial_key="results.pattern.edit_permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        pattern = self.pattern_repository.get_pattern_by_id(
            thread_id=thread.thread_id,
            p_index=event.pattern_id,
        )
        if pattern is None:
            return self.localizer.thread_result(
                "results.pattern.not_found_id",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        new_text = pattern.regex if event.pattern_text is None else event.pattern_text.strip()
        if not new_text:
            raise ValueError(self._text(thread, "results.pattern.empty_pattern"))

        new_is_regex = pattern.is_regex if event.is_regex is None else event.is_regex
        if new_is_regex:
            re.compile(new_text)

        new_channel_scope_mode = pattern.channel_scope_mode if event.channel_scope_mode is None else event.channel_scope_mode
        new_user_scope_mode = pattern.user_scope_mode if event.user_scope_mode is None else event.user_scope_mode
        new_sub_state = pattern.sub_state if event.sub_state is None else event.sub_state
        new_offline_state = pattern.offline_state if event.offline_state is None else event.offline_state
        new_case_sensitive = pattern.case_sensitive if event.case_sensitive is None else event.case_sensitive
        if event.clear_color:
            new_color = None
        elif event.color is None:
            new_color = pattern.color
        else:
            new_color = event.color.strip()
        if new_color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", new_color):
            raise ValueError(self._text(thread, "results.pattern.invalid_color"))
        new_priority = pattern.priority if event.priority is None else event.priority
        if not 0 <= new_priority <= 9:
            raise ValueError(self._text(thread, "results.pattern.invalid_priority"))

        scoped_channels, scoped_users = await self._filter_resolver().resolve_pattern_edit_filters(
            event,
            thread,
            pattern,
        )

        existing = self.pattern_repository.find_exact_pattern(
            thread_id=thread.thread_id,
            regex=new_text,
            channel_scope_mode=new_channel_scope_mode,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=new_user_scope_mode,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=new_sub_state,
            offline_state=new_offline_state,
            is_regex=new_is_regex,
            case_sensitive=new_case_sensitive,
        )
        if existing is not None and existing.p_index != pattern.p_index:
            return self.localizer.thread_result(
                "results.pattern.already_exists_other",
                thread=thread,
                ID=existing.p_index,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.pattern_repository.update_pattern(
            thread_id=thread.thread_id,
            p_index=pattern.p_index,
            regex=new_text,
            channel_scope_mode=new_channel_scope_mode,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=new_user_scope_mode,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=new_sub_state,
            offline_state=new_offline_state,
            is_regex=new_is_regex,
            case_sensitive=new_case_sensitive,
            color=new_color,
            priority=new_priority,
        )
        assert updated is not None
        old_channel_logins = await self._filter_resolver().resolve_display_names_from_ids(
            pattern.channel_scope_ids,
        )
        old_user_logins = await self._filter_resolver().resolve_display_names_from_ids(
            pattern.user_scope_ids,
        )
        return DiscordCommandResult(
            title=self.localizer.text("results.pattern.updated_title", language=thread.language),
            message=self._presenter().format_pattern_changes(
                before=pattern,
                after=updated,
                old_channel_logins=old_channel_logins,
                new_channel_logins=tuple(channel.display_name for channel in scoped_channels),
                old_user_logins=old_user_logins,
                new_user_logins=tuple(user.display_name for user in scoped_users),
                language=thread.language,
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _locate_pattern_for_removal(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> PatternRecord | None:
        """Locate the exact rule that should be removed."""
        if event.pattern_id is not None:
            return self.pattern_repository.get_pattern_by_id(
                thread_id=thread.thread_id,
                p_index=event.pattern_id,
            )
        raise ValueError(self._text(thread, "results.pattern.missing_stable_id"))

    def _event_result(
        self,
        event: DiscordPatternRequestedEvent | DiscordPatternEditRequestedEvent,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        return self.localizer.thread_result(
            key,
            thread=thread,
            style=style,
            ephemeral=ephemeral,
            **placeholders,
        )

    def _text(
        self,
        thread: ThreadRecord | None,
        key: str,
        **placeholders: object,
    ) -> str:
        return self.localizer.text(
            key,
            language=self.localizer.language_for_thread(thread),
            **placeholders,
        )

    def _pattern_type(self, is_regex: bool, *, language: str) -> str:
        return self._presenter().pattern_type(is_regex, language=language)

    def _presenter(self) -> PatternCommandPresenter:
        return PatternCommandPresenter(self.localizer)

    def _filter_resolver(self) -> PatternFilterResolver:
        return PatternFilterResolver(
            channel_repository=self.channel_repository,
            twitch_api=self.twitch_api,
            tracked_user_repository=self.tracked_user_repository,
            localizer=self.localizer,
        )

    @staticmethod
    def _default_priority_for(
        *,
        channel_scope_mode: str,
        user_scope_mode: str,
        sub_state: str,
        offline_state: str,
    ) -> int:
        """Estimate a sensible default priority from rule specificity."""
        priority = 0
        if channel_scope_mode == "only_selected":
            priority += 2
        elif channel_scope_mode == "all_except_selected":
            priority += 1

        if user_scope_mode == "only_selected":
            priority += 4
        elif user_scope_mode == "all_except_selected":
            priority += 2
        elif user_scope_mode == "all_tracked_except_selected":
            priority += 3

        if sub_state != "all":
            priority += 1
        if offline_state != "both":
            priority += 1
        return min(priority, 9)
