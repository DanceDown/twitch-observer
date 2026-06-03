"""Business logic for `/ping` add/edit/remove requests."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.gateways.twitch_api import TwitchAPIConfigurationError, TwitchChannelNotFoundError
from src.database.connection import (
    ChannelRepository,
    PatternRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
    UserPermissionRepository,
)
from src.discord_results import build_thread_result
from src.events.event_types import (
    AddPatternCommand,
    ChannelScopeMode,
    DiscordCommandResult,
    DiscordResultStyle,
    EditPatternCommand,
    OfflineScope,
    RemovePatternCommand,
    SetPatternEnabledCommand,
    SubscriptionScope,
    UserScopeMode,
)
from src.localization import Localizer
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.patterns.display_index import PatternDisplayIndexResolver
from src.services.patterns.filters import PatternFilterResolver
from src.services.patterns.presentation import PatternCommandPresenter
from src.services.twitch_gateways import TwitchDirectoryGateway
from src.utils.permissions import ObserverPermission
from src.discord_results import discord_user_mention
from src.utils.async_utils import resolve_awaitable

logger = logging.getLogger(__name__)

PatternCommand = AddPatternCommand | RemovePatternCommand | SetPatternEnabledCommand | EditPatternCommand


@dataclass(slots=True, frozen=True)
class _PatternPermissionCommand:
    discord_channel_id: int
    requester_id: int


@dataclass(slots=True)
class PatternCommandService:
    """Handle `/ping` add/edit/remove requests from Discord."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchDirectoryGateway
    tracked_user_repository: TrackedUserRepository | None = None
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    _runner: CommandExecutionRunner = field(init=False, repr=False)
    _guards: ThreadCommandGuards = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._runner = CommandExecutionRunner(
            localizer=self.localizer,
            resolve_thread=self._resolve_thread,
            validation_error_key="results.pattern.validation_error",
            twitch_api_error_key="results.pattern.twitch_api_error",
            unexpected_error_key="results.pattern.unexpected_error",
        )
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=None,
            localizer=self.localizer,
            not_joined_key="results.pattern.not_joined",
        )

    async def handle_add_command(self, command: AddPatternCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._add_pattern_command(command),
            logger_=logger,
            validation_exceptions=(
                ValueError,
                re.error,
                TwitchAPIConfigurationError,
                TwitchChannelNotFoundError,
            ),
        )

    async def handle_remove_command(self, command: RemovePatternCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._remove_pattern_command(command),
            logger_=logger,
            validation_exceptions=(
                ValueError,
                re.error,
                TwitchAPIConfigurationError,
                TwitchChannelNotFoundError,
            ),
        )

    async def handle_set_enabled_command(self, command: SetPatternEnabledCommand) -> DiscordCommandResult:
        operation = self._enable_pattern(command) if command.enabled else self._disable_pattern(command)
        return await self._runner.run(
            command,
            lambda: operation,
            logger_=logger,
            validation_exceptions=(
                ValueError,
                re.error,
                TwitchAPIConfigurationError,
                TwitchChannelNotFoundError,
            ),
        )

    async def handle_edit_command(self, command: EditPatternCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._edit_pattern(command),
            logger_=logger,
            validation_exceptions=(
                ValueError,
                re.error,
                TwitchAPIConfigurationError,
                TwitchChannelNotFoundError,
            ),
        )

    async def _add_pattern_command(self, command: AddPatternCommand) -> DiscordCommandResult:
        thread = await self._ensure_pattern_permission(
            command.discord_channel_id,
            command.requester_id,
            required_permission=ObserverPermission.MANAGE_PATTERNS,
            denial_key="results.pattern.manage_permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread
        return await self._add_pattern(command, thread)

    async def _remove_pattern_command(self, command: RemovePatternCommand) -> DiscordCommandResult:
        thread = await self._ensure_pattern_permission(
            command.discord_channel_id,
            command.requester_id,
            required_permission=ObserverPermission.MANAGE_PATTERNS,
            denial_key="results.pattern.manage_permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread
        return await self._remove_pattern(command, thread)

    async def _ensure_pattern_permission(
        self,
        discord_channel_id: int,
        requester_id: int,
        *,
        required_permission: ObserverPermission,
        denial_key: str,
    ) -> ThreadRecord | DiscordCommandResult:
        return await self._guards.require_permission(
            _PatternPermissionCommand(discord_channel_id=discord_channel_id, requester_id=requester_id),
            permission=required_permission,
            denial_key=denial_key,
        )

    async def _add_pattern(
        self,
        command: AddPatternCommand,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        logger.debug("Adding pattern request: %r", command)
        text = command.pattern_text.strip()
        if not text:
            raise ValueError(self._text(thread, "results.pattern.empty_pattern"))
        if command.color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", command.color.strip()):
            raise ValueError(self._text(thread, "results.pattern.invalid_color"))
        if command.is_regex:
            re.compile(text)
        if command.priority is not None and not 0 <= command.priority <= 9:
            raise ValueError(self._text(thread, "results.pattern.invalid_priority"))

        scoped_channels, scoped_users = await self._filter_resolver().resolve_filters(
            channel_scope_mode=command.channel_scope_mode,
            twitch_channel_logins=command.twitch_channel_logins,
            user_scope_mode=command.user_scope_mode,
            twitch_user_logins=command.twitch_user_logins,
            thread=thread,
        )

        existing = await resolve_awaitable(
            self.pattern_repository.find_exact_pattern(
                thread_id=thread.thread_id,
                regex=text,
                channel_scope_mode=command.channel_scope_mode.value,
                channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
                user_scope_mode=command.user_scope_mode.value,
                user_scope_ids=tuple(user.user_id for user in scoped_users),
                sub_state=command.sub_state.value,
                offline_state=command.offline_state.value,
                is_regex=command.is_regex,
                case_sensitive=command.case_sensitive,
            )
        )
        if existing is not None:
            display_id = self._display_index(thread.thread_id, existing.pattern_id) or existing.pattern_id
            return build_thread_result(
                self.localizer,
                "results.pattern.already_exists",
                thread=thread,
                ID=display_id,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        created = self.pattern_repository.add_pattern(
            thread_id=thread.thread_id,
            regex=text,
            channel_scope_mode=command.channel_scope_mode.value,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=command.user_scope_mode.value,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=command.sub_state.value,
            offline_state=command.offline_state.value,
            is_regex=command.is_regex,
            case_sensitive=command.case_sensitive,
            color=command.color.strip() if command.color else None,
            disabled=command.disabled,
            priority=(
                command.priority
                if command.priority is not None
                else self._default_priority_for(
                    channel_scope_mode=command.channel_scope_mode,
                    user_scope_mode=command.user_scope_mode,
                    sub_state=command.sub_state,
                    offline_state=command.offline_state,
                )
            ),
        )
        display_id = await self._display_index(thread.thread_id, created.pattern_id) or created.pattern_id
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
            self.localizer,
            "results.pattern.added_result",
            thread=thread,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            ID=display_id,
            SUMMARY=self._presenter().format_pattern_summary(
                pattern=created,
                channel_logins=tuple(self._profile_item(channel.display_name, channel.login) for channel in scoped_channels),
                user_logins=tuple(self._profile_item(user.display_name, user.login) for user in scoped_users),
                language=thread.language,
                key_prefix="results.pattern.added_result.summary",
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _remove_pattern(
        self,
        command: RemovePatternCommand,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        logger.debug("Removing pattern request: %r", command)
        pattern = await resolve_awaitable(
            self.pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
        )
        if pattern is None:
            return build_thread_result(
                self.localizer,
                "results.pattern.not_found_remove",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        display_id = await self._display_index(thread.thread_id, pattern.pattern_id) or pattern.pattern_id
        self.pattern_repository.remove_pattern(thread_id=pattern.thread_id, pattern_id=pattern.pattern_id)
        logger.debug("Removed pattern thread_id=%s pattern_id=%s regex=%r", pattern.thread_id, pattern.pattern_id, pattern.regex)
        return build_thread_result(
            self.localizer,
            "results.pattern.removed_result",
            thread=thread,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            ID=display_id,
            TEXT=pattern.regex,
            PING_MODE=self._pattern_mode(pattern.is_regex, language=thread.language, scope="results.pattern.removed_result"),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _disable_pattern(self, command: SetPatternEnabledCommand) -> DiscordCommandResult:
        thread = await self._ensure_pattern_permission(
            command.discord_channel_id,
            command.requester_id,
            required_permission=ObserverPermission.TOGGLE_PATTERNS,
            denial_key="results.pattern.toggle_permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        logger.debug("Disabling pattern request: %r", command)
        pattern = await resolve_awaitable(
            self.pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
        )
        if pattern is None:
            return build_thread_result(
                self.localizer,
                "results.pattern.not_found_disable",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if pattern.disabled:
            display_id = await self._display_index(thread.thread_id, pattern.pattern_id) or pattern.pattern_id
            return build_thread_result(
                self.localizer,
                "results.pattern.already_disabled",
                thread=thread,
                ID=display_id,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        updated = self.pattern_repository.set_pattern_disabled(
            thread_id=pattern.thread_id,
            pattern_id=pattern.pattern_id,
            disabled=True,
        )
        if updated is None:
            raise RuntimeError("Pattern repository returned no row for disable.")
        display_id = await self._display_index(thread.thread_id, updated.pattern_id) or updated.pattern_id
        return build_thread_result(
            self.localizer,
            "results.pattern.disabled_result",
            thread=thread,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            ID=display_id,
            TEXT=updated.regex,
            PING_MODE=self._pattern_mode(updated.is_regex, language=thread.language, scope="results.pattern.disabled_result"),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _enable_pattern(self, command: SetPatternEnabledCommand) -> DiscordCommandResult:
        thread = await self._ensure_pattern_permission(
            command.discord_channel_id,
            command.requester_id,
            required_permission=ObserverPermission.TOGGLE_PATTERNS,
            denial_key="results.pattern.toggle_permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        logger.debug("Enabling pattern request: %r", command)
        pattern = await resolve_awaitable(
            self.pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
        )
        if pattern is None:
            return build_thread_result(
                self.localizer,
                "results.pattern.not_found_enable",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not pattern.disabled:
            display_id = await self._display_index(thread.thread_id, pattern.pattern_id) or pattern.pattern_id
            return build_thread_result(
                self.localizer,
                "results.pattern.already_enabled",
                thread=thread,
                ID=display_id,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        updated = self.pattern_repository.set_pattern_disabled(
            thread_id=pattern.thread_id,
            pattern_id=pattern.pattern_id,
            disabled=False,
        )
        if updated is None:
            raise RuntimeError("Pattern repository returned no row for enable.")
        display_id = await self._display_index(thread.thread_id, updated.pattern_id) or updated.pattern_id
        return build_thread_result(
            self.localizer,
            "results.pattern.enabled_result",
            thread=thread,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            ID=display_id,
            TEXT=updated.regex,
            PING_MODE=self._pattern_mode(updated.is_regex, language=thread.language, scope="results.pattern.enabled_result"),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _edit_pattern(self, command: EditPatternCommand) -> DiscordCommandResult:
        thread = await self._ensure_pattern_permission(
            command.discord_channel_id,
            command.requester_id,
            required_permission=ObserverPermission.MANAGE_PATTERNS,
            denial_key="results.pattern.edit_permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        pattern = await resolve_awaitable(
            self.pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
        )
        if pattern is None:
            return build_thread_result(
                self.localizer,
                "results.pattern.not_found_id",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        new_text = pattern.regex if command.pattern_text is None else command.pattern_text.strip()
        if not new_text:
            raise ValueError(self._text(thread, "results.pattern.empty_pattern"))

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
            raise ValueError(self._text(thread, "results.pattern.invalid_color"))
        new_priority = pattern.priority if command.priority is None else command.priority
        if not 0 <= new_priority <= 9:
            raise ValueError(self._text(thread, "results.pattern.invalid_priority"))

        scoped_channels, scoped_users = await self._filter_resolver().resolve_pattern_edit_filters(
            channel_scope_mode=command.channel_scope_mode,
            twitch_channel_logins=command.twitch_channel_logins,
            user_scope_mode=command.user_scope_mode,
            twitch_user_logins=command.twitch_user_logins,
            thread=thread,
            pattern=pattern,
        )

        existing = await resolve_awaitable(
            self.pattern_repository.find_exact_pattern(
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
        )
        if existing is not None and existing.pattern_id != pattern.pattern_id:
            display_id = await self._display_index(thread.thread_id, existing.pattern_id) or existing.pattern_id
            return build_thread_result(
                self.localizer,
                "results.pattern.already_exists_other",
                thread=thread,
                ID=display_id,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.pattern_repository.update_pattern(
            thread_id=thread.thread_id,
            pattern_id=pattern.pattern_id,
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
        if updated is None:
            raise RuntimeError("Pattern repository returned no row for update.")
        display_id = await self._display_index(thread.thread_id, updated.pattern_id) or updated.pattern_id
        old_channel_logins = await self._filter_resolver().resolve_profile_items_from_ids(
            pattern.channel_scope_ids,
        )
        old_user_logins = await self._filter_resolver().resolve_profile_items_from_ids(
            pattern.user_scope_ids,
        )
        return build_thread_result(
            self.localizer,
            "results.pattern.updated_result",
            thread=thread,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            ID=display_id,
            SUMMARY=self._presenter().format_pattern_changes(
                before=pattern,
                after=updated,
                old_channel_logins=old_channel_logins,
                new_channel_logins=tuple(self._profile_item(channel.display_name, channel.login) for channel in scoped_channels),
                old_user_logins=old_user_logins,
                new_user_logins=tuple(self._profile_item(user.display_name, user.login) for user in scoped_users),
                language=thread.language,
                key_prefix="results.pattern.updated_result.summary",
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
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

    def _pattern_mode(self, is_regex: bool, *, language: str, scope: str) -> str:
        suffix = "regex" if is_regex else "word"
        key = f"{scope}.mode_value.{suffix}"
        return self.localizer.text(key, language=language)

    def _presenter(self) -> PatternCommandPresenter:
        return PatternCommandPresenter(self.localizer)

    def _filter_resolver(self) -> PatternFilterResolver:
        return PatternFilterResolver(
            channel_repository=self.channel_repository,
            twitch_api=self.twitch_api,
            tracked_user_repository=self.tracked_user_repository,
            localizer=self.localizer,
        )

    async def _display_index(self, thread_id: int, pattern_id: int) -> int | None:
        return await PatternDisplayIndexResolver(self.pattern_repository).resolve(
            thread_id=thread_id,
            pattern_id=pattern_id,
        )

    @staticmethod
    def _profile_item(display_name: str, login: str) -> dict[str, str]:
        return {"DISPLAY_NAME": display_name, "LOGIN": login}

    async def _resolve_thread(self, command: PatternCommand) -> ThreadRecord | None:
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(command.discord_channel_id))

    @staticmethod
    def _default_priority_for(
        *,
        channel_scope_mode: ChannelScopeMode,
        user_scope_mode: UserScopeMode,
        sub_state: SubscriptionScope,
        offline_state: OfflineScope,
    ) -> int:
        """Estimate a sensible default priority from rule specificity."""
        priority = 0
        if channel_scope_mode is ChannelScopeMode.ONLY_SELECTED:
            priority += 2
        elif channel_scope_mode is ChannelScopeMode.ALL_EXCEPT_SELECTED:
            priority += 1

        if user_scope_mode is UserScopeMode.ONLY_SELECTED:
            priority += 4
        elif user_scope_mode is UserScopeMode.ALL_EXCEPT_SELECTED:
            priority += 2
        elif user_scope_mode is UserScopeMode.ALL_TRACKED_EXCEPT_SELECTED:
            priority += 3

        if sub_state is not SubscriptionScope.ALL:
            priority += 1
        if offline_state is not OfflineScope.BOTH:
            priority += 1
        return min(priority, 9)
