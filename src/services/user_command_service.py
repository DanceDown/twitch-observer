"""Business logic for tracked Twitch-user management commands."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.database.connection import ThreadRepository, TrackedUserRepository, UserPermissionRepository
from src.discord_results import build_thread_result, discord_user_mention
from src.events.event_types import AddTrackedUserCommand, DiscordCommandResult, DiscordResultStyle, RemoveTrackedUserCommand
from src.localization import Localizer
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.twitch_gateways import TwitchUserLookup
from src.utils.permissions import ObserverPermission
from src.utils.async_utils import resolve_awaitable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserCommandService:
    """Handle tracked Twitch-user add/remove requests from Discord."""

    thread_repository: ThreadRepository
    tracked_user_repository: TrackedUserRepository
    twitch_user_lookup: TwitchUserLookup
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    permission_repository: UserPermissionRepository | None = None
    _runner: CommandExecutionRunner = field(init=False, repr=False)
    _guards: ThreadCommandGuards = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._runner = CommandExecutionRunner(
            localizer=self.localizer,
            resolve_thread=self._resolve_thread,
            validation_error_key="results.user.validation_error",
            twitch_api_error_key="results.user.twitch_api_error",
            unexpected_error_key="results.user.unexpected_error",
        )
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=None,
            localizer=self.localizer,
            not_joined_key="results.user.not_joined",
        )

    async def handle_add(self, command: AddTrackedUserCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._add_user(command), logger_=logger)

    async def handle_remove(self, command: RemoveTrackedUserCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._remove_user(command), logger_=logger)

    async def _add_user(self, command: AddTrackedUserCommand) -> DiscordCommandResult:
        thread = await self._guards.require_permission(
            command,
            permission=ObserverPermission.MANAGE_PATTERNS,
            denial_key="results.user.permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        twitch_user = await self.twitch_user_lookup.get_user_by_login(command.twitch_user_login)
        existing = await resolve_awaitable(self.tracked_user_repository.get_by_thread_and_twitch_user(thread.thread_id, twitch_user.user_id))
        if existing is not None:
            return build_thread_result(
                self.localizer,
                "results.user.already_added",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )
        self.tracked_user_repository.add_user(thread.thread_id, twitch_user.user_id)
        return build_thread_result(
            self.localizer,
            "results.user.added",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            DISPLAY_NAME=twitch_user.display_name,
            LOGIN=twitch_user.login,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    async def _remove_user(self, command: RemoveTrackedUserCommand) -> DiscordCommandResult:
        thread = await self._guards.require_permission(
            command,
            permission=ObserverPermission.MANAGE_PATTERNS,
            denial_key="results.user.permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        twitch_user = await self.twitch_user_lookup.get_user_by_login(command.twitch_user_login)
        existing = await resolve_awaitable(self.tracked_user_repository.get_by_thread_and_twitch_user(thread.thread_id, twitch_user.user_id))
        if existing is None:
            return build_thread_result(
                self.localizer,
                "results.user.not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )
        if await resolve_awaitable(self.tracked_user_repository.count_pattern_scope_references(thread_id=thread.thread_id, twitch_user_id=twitch_user.user_id)) > 0:
            return build_thread_result(
                self.localizer,
                "results.user.in_use",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )
        self.tracked_user_repository.remove_user(thread.thread_id, twitch_user.user_id)
        return build_thread_result(
            self.localizer,
            "results.user.removed",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            DISPLAY_NAME=twitch_user.display_name,
            LOGIN=twitch_user.login,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    async def _resolve_thread(self, command: AddTrackedUserCommand | RemoveTrackedUserCommand):
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(command.discord_channel_id))
