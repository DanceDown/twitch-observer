"""Business logic for managing auto-reply configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
    UserPermissionRepository,
)
from src.events.commands import (
    AddChannelEventReplyCommand,
    AddPatternReplyCommand,
    RemoveChannelEventReplyCommand,
    RemovePatternReplyCommand,
    SetChannelEventReplyEnabledCommand,
    SetPatternReplyEnabledCommand,
)
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.twitch_gateways import TwitchChannelStateLookup
from src.utils.permissions import ObserverPermission

from .command_operations import handle_event_action, handle_pattern_action
from .command_support import ReplyCommandSupport

PatternReplyCommand = AddPatternReplyCommand | RemovePatternReplyCommand | SetPatternReplyEnabledCommand
EventReplyCommand = AddChannelEventReplyCommand | RemoveChannelEventReplyCommand | SetChannelEventReplyEnabledCommand
ReplyCommand = PatternReplyCommand | EventReplyCommand
logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _ReplyPermissionCommand:
    discord_channel_id: int
    requester_id: int


@dataclass(slots=True, frozen=True)
class ReplyEventConfiguration:
    """Dependencies needed only for adapter-event reply commands."""

    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    twitch_api: TwitchChannelStateLookup


@dataclass(slots=True)
class ReplyCommandService:
    """Handle `/reply` add/remove/disable/enable requests."""

    thread_repository: ThreadRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    account_repository: TwitchAccountRepository
    event_configuration: ReplyEventConfiguration | None = None
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    _runner: CommandExecutionRunner = field(init=False, repr=False)
    _guards: ThreadCommandGuards = field(init=False, repr=False)
    _support: ReplyCommandSupport = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._runner = CommandExecutionRunner(
            localizer=self.localizer,
            resolve_thread=self._resolve_thread,
            validation_error_key="results.reply.validation_error",
            twitch_api_error_key="results.reply.twitch_api_error",
            unexpected_error_key="results.reply.unexpected_error",
        )
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=self.account_repository,
            localizer=self.localizer,
            not_joined_key="results.reply.not_joined",
        )
        self._support = ReplyCommandSupport(
            pattern_repository=self.pattern_repository,
            localizer=self.localizer,
        )

    async def handle_add_pattern_command(self, command: AddPatternReplyCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._handle_pattern_action(command, action="add"),
            logger_=logger,
        )

    async def handle_remove_pattern_command(self, command: RemovePatternReplyCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._handle_pattern_action(command, action="remove"),
            logger_=logger,
        )

    async def handle_set_pattern_enabled_command(self, command: SetPatternReplyEnabledCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._handle_pattern_action(command, action="enable" if command.enabled else "disable"),
            logger_=logger,
        )

    async def handle_add_event_command(self, command: AddChannelEventReplyCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._handle_adapter_event_action(command, action="add"),
            logger_=logger,
        )

    async def handle_remove_event_command(self, command: RemoveChannelEventReplyCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._handle_adapter_event_action(command, action="remove"),
            logger_=logger,
        )

    async def handle_set_event_enabled_command(self, command: SetChannelEventReplyEnabledCommand) -> DiscordCommandResult:
        return await self._runner.run(
            command,
            lambda: self._handle_adapter_event_action(command, action="enable" if command.enabled else "disable"),
            logger_=logger,
        )

    async def _handle_pattern_action(
        self,
        command: PatternReplyCommand,
        *,
        action: str,
    ) -> DiscordCommandResult:
        if action in {"add", "remove"}:
            required_permission = ObserverPermission.MANAGE_REPLIES
            denial_key = "results.reply.manage_permission_denied"
        else:
            required_permission = ObserverPermission.TOGGLE_REPLIES
            denial_key = "results.reply.toggle_permission_denied"

        thread = await self._ensure_thread_permission(
            command.discord_channel_id,
            command.requester_id,
            required_permission=required_permission,
            denial_key=denial_key,
        )
        if isinstance(thread, DiscordCommandResult):
            return thread
        return await handle_pattern_action(
            command=command,
            action=action,
            thread=thread,
            pattern_repository=self.pattern_repository,
            reply_repository=self.reply_repository,
            account_repository=self.account_repository,
            localizer=self.localizer,
            support=self._support,
        )

    async def _handle_adapter_event_action(
        self,
        command: EventReplyCommand,
        *,
        action: str,
    ) -> DiscordCommandResult:
        if action in {"add", "remove"}:
            required_permission = ObserverPermission.MANAGE_REPLIES
            denial_key = "results.reply.manage_permission_denied"
        else:
            required_permission = ObserverPermission.TOGGLE_REPLIES
            denial_key = "results.reply.toggle_permission_denied"

        thread = await self._ensure_thread_permission(
            command.discord_channel_id,
            command.requester_id,
            required_permission=required_permission,
            denial_key=denial_key,
        )
        if isinstance(thread, DiscordCommandResult):
            return thread
        return await handle_event_action(
            command=command,
            action=action,
            thread=thread,
            event_configuration=self.event_configuration,
            account_repository=self.account_repository,
            localizer=self.localizer,
            support=self._support,
        )

    async def _ensure_thread_permission(
        self,
        discord_channel_id: int,
        requester_id: int,
        *,
        required_permission: ObserverPermission,
        denial_key: str,
    ) -> ThreadRecord | DiscordCommandResult:
        return await self._guards.require_permission(
            _ReplyPermissionCommand(discord_channel_id=discord_channel_id, requester_id=requester_id),
            permission=required_permission,
            denial_key=denial_key,
        )

    async def _resolve_thread(self, command: ReplyCommand) -> ThreadRecord | None:
        return await self.thread_repository.get_by_discord_channel_id(command.discord_channel_id)
