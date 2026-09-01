"""Business logic for `/ping` add/edit/remove requests."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.database.connection import (
    ChannelRepository,
    PatternRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
    UserPermissionRepository,
)
from src.events.commands import AddPatternCommand, EditPatternCommand, RemovePatternCommand, SetPatternEnabledCommand
from src.events.discord_results import DiscordCommandResult
from src.gateways.twitch_api import TwitchAPIConfigurationError, TwitchChannelNotFoundError
from src.localization import Localizer
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.twitch_gateways import TwitchDirectoryGateway
from src.utils.permissions import ObserverPermission

from .command_operations import add_pattern, edit_pattern, remove_pattern, set_pattern_enabled
from .command_support import PatternCommandSupport

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
    _support: PatternCommandSupport = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build shared guards and pattern support after dependency injection."""
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
        self._support = PatternCommandSupport(
            channel_repository=self.channel_repository,
            pattern_repository=self.pattern_repository,
            twitch_api=self.twitch_api,
            tracked_user_repository=self.tracked_user_repository,
            localizer=self.localizer,
        )

    async def handle_add_command(self, command: AddPatternCommand) -> DiscordCommandResult:
        """Create a Twitch chat ping pattern for the Discord context."""
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
        """Remove a Twitch chat ping pattern from the Discord context."""
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
        """Enable or disable a Twitch chat ping pattern."""
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
        """Edit an existing Twitch chat ping pattern."""
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
        return await add_pattern(
            command=command,
            thread=thread,
            pattern_repository=self.pattern_repository,
            localizer=self.localizer,
            support=self._support,
        )

    async def _remove_pattern(
        self,
        command: RemovePatternCommand,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        return await remove_pattern(
            command=command,
            thread=thread,
            pattern_repository=self.pattern_repository,
            localizer=self.localizer,
            support=self._support,
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
        return await set_pattern_enabled(
            command=command,
            thread=thread,
            pattern_repository=self.pattern_repository,
            localizer=self.localizer,
            support=self._support,
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
        return await set_pattern_enabled(
            command=command,
            thread=thread,
            pattern_repository=self.pattern_repository,
            localizer=self.localizer,
            support=self._support,
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
        return await edit_pattern(
            command=command,
            thread=thread,
            pattern_repository=self.pattern_repository,
            localizer=self.localizer,
            support=self._support,
        )

    async def _resolve_thread(self, command: PatternCommand) -> ThreadRecord | None:
        return await self.thread_repository.get_by_discord_channel_id(command.discord_channel_id)
