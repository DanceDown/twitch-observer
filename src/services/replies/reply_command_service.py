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
from src.discord_results import build_thread_result, discord_user_mention
from src.events.event_types import (
    AddChannelEventReplyCommand,
    AddPatternReplyCommand,
    DiscordCommandResult,
    DiscordResultStyle,
    RemoveChannelEventReplyCommand,
    RemovePatternReplyCommand,
    SetChannelEventReplyEnabledCommand,
    SetPatternReplyEnabledCommand,
)
from src.localization import Localizer
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.patterns.display_index import PatternDisplayIndexResolver
from src.services.twitch_gateways import TwitchChannelStateLookup
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
)
from src.utils.permissions import ObserverPermission
from src.utils.async_utils import resolve_awaitable

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

        pattern = await resolve_awaitable(
            self.pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=command.pattern_id)
        )
        if pattern is None:
            return build_thread_result(
                self.localizer,
                "results.reply.pattern_not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        display_id = await self._display_index(thread.thread_id, pattern.pattern_id) or pattern.pattern_id
        if action == "add":
            linked_account = (
                await resolve_awaitable(self.account_repository.get_by_account_id(thread.account_id))
                if thread.account_id is not None
                else None
            )
            if linked_account is None:
                return build_thread_result(
                    self.localizer,
                    "results.reply.no_linked_account",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )

            message = command.message.strip()
            if not message:
                raise ValueError(self.localizer.text("results.reply.pattern_add_empty_message", language=thread.language))
            if len(message) > 500:
                raise ValueError(self.localizer.text("results.reply.pattern_add_message_too_long", language=thread.language))
            existing_reply = await resolve_awaitable(
                self.reply_repository.get_by_pattern(thread_id=thread.thread_id, pattern_id=pattern.pattern_id)
            )
            if existing_reply is not None:
                return build_thread_result(
                    self.localizer,
                    "results.reply.already_exists",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            created = self.reply_repository.add_reply(
                thread_id=thread.thread_id,
                pattern_id=pattern.pattern_id,
                reply_message=message,
                reply_as_reply=command.reply_as_reply,
            )
            if created is None:
                raise RuntimeError("Reply repository returned no row for add_reply.")
            return build_thread_result(
                self.localizer,
                "results.reply.added_pattern",
                thread=thread,
                ID=display_id,
                MODE=self.localizer.text(
                    "results.reply.added_pattern.mode.reply" if created.reply_as_reply else "results.reply.added_pattern.mode.message",
                    language=thread.language,
                ),
                MESSAGE=created.reply_message,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )

        existing_reply = await resolve_awaitable(
            self.reply_repository.get_by_pattern(thread_id=thread.thread_id, pattern_id=pattern.pattern_id)
        )
        if existing_reply is None:
            return build_thread_result(
                self.localizer,
                "results.reply.none_configured",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        if action == "remove":
            cleared = self.reply_repository.remove_reply(thread_id=thread.thread_id, pattern_id=pattern.pattern_id)
            if cleared is None:
                raise RuntimeError("Reply repository returned no row for remove_reply.")
            return build_thread_result(
                self.localizer,
                "results.reply.removed_pattern",
                thread=thread,
                ID=display_id,
                MESSAGE=existing_reply.reply_message,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )

        if action == "disable":
            if existing_reply.disabled:
                return build_thread_result(
                    self.localizer,
                    "results.reply.already_disabled",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            disabled_reply = self.reply_repository.set_reply_disabled(
                thread_id=thread.thread_id,
                pattern_id=pattern.pattern_id,
                disabled=True,
            )
            if disabled_reply is None:
                raise RuntimeError("Reply repository returned no row for disable pattern reply.")
            return build_thread_result(
                self.localizer,
                "results.reply.disabled_pattern",
                thread=thread,
                ID=display_id,
                MESSAGE=disabled_reply.reply_message,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )

        if action == "enable":
            if not existing_reply.disabled:
                return build_thread_result(
                    self.localizer,
                    "results.reply.already_enabled",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            enabled_reply = self.reply_repository.set_reply_disabled(
                thread_id=thread.thread_id,
                pattern_id=pattern.pattern_id,
                disabled=False,
            )
            if enabled_reply is None:
                raise RuntimeError("Reply repository returned no row for enable pattern reply.")
            return build_thread_result(
                self.localizer,
                "results.reply.enabled_pattern",
                thread=thread,
                ID=display_id,
                MESSAGE=enabled_reply.reply_message,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )

        raise ValueError(self.localizer.text("results.reply.pattern_action_unsupported", language=thread.language))

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

        event_configuration = self.event_configuration
        if event_configuration is None:
            raise ValueError(self.localizer.text("results.reply.event_unavailable", language=thread.language))

        adapter_event = next(
            (
                item
                for item in await resolve_awaitable(
                    event_configuration.adapter_event_repository.list_events_for_thread(
                        thread.thread_id,
                        include_disabled=True,
                    )
                )
                if item.event_id == command.adapter_event_id
            ),
            None,
        )
        if adapter_event is None:
            return build_thread_result(
                self.localizer,
                "results.reply.event_not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        state_label = STREAM_EVENT_KEY_TO_STATE.get(adapter_event.event_key)
        if adapter_event.adapter_key != TWITCH_ADAPTER_KEY or adapter_event.subject_type != CHANNEL_SUBJECT_TYPE or state_label is None:
            raise ValueError(self.localizer.text("results.reply.unsupported_event", language=thread.language))

        cached = event_configuration.twitch_api.get_cached_user_by_id(adapter_event.subject_id.strip())
        twitch_channel = cached if cached is not None else await event_configuration.twitch_api.get_channel_by_id(adapter_event.subject_id)
        channel_display_name = twitch_channel.display_name
        channel_login = twitch_channel.login

        existing_reply = await resolve_awaitable(
            event_configuration.adapter_event_action_repository.get_action(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
            )
        )

        if action == "add":
            linked_account = (
                await resolve_awaitable(self.account_repository.get_by_account_id(thread.account_id))
                if thread.account_id is not None
                else None
            )
            if linked_account is None:
                return build_thread_result(
                    self.localizer,
                    "results.reply.no_linked_account",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            message = command.message.strip()
            if not message:
                raise ValueError(self.localizer.text("results.reply.event_add_empty_message", language=thread.language))
            if len(message) > 500:
                raise ValueError(self.localizer.text("results.reply.event_add_message_too_long", language=thread.language))
            created = event_configuration.adapter_event_action_repository.upsert_action(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                message_template=message,
                reply_as_reply=False,
            )
            return build_thread_result(
                self.localizer,
                "results.reply.added_event",
                thread=thread,
                DISPLAY_NAME=channel_display_name,
                LOGIN=channel_login,
                STATE=state_label,
                MESSAGE=created.message_template or "",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )

        if existing_reply is None:
            return build_thread_result(
                self.localizer,
                "results.reply.none_configured_event",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        if action == "remove":
            removed = event_configuration.adapter_event_action_repository.remove_action(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
            )
            if removed is None:
                raise RuntimeError("Reply repository returned no row for remove adapter-event action.")
            return build_thread_result(
                self.localizer,
                "results.reply.removed_event",
                thread=thread,
                DISPLAY_NAME=channel_display_name,
                LOGIN=channel_login,
                STATE=state_label,
                MESSAGE=existing_reply.message_template or "",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )

        if action == "disable":
            if existing_reply.disabled:
                return build_thread_result(
                    self.localizer,
                    "results.reply.already_disabled",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            disabled_reply = event_configuration.adapter_event_action_repository.set_action_disabled(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                disabled=True,
            )
            if disabled_reply is None:
                raise RuntimeError("Reply repository returned no row for disable adapter-event action.")
            return build_thread_result(
                self.localizer,
                "results.reply.disabled_event",
                thread=thread,
                DISPLAY_NAME=channel_display_name,
                LOGIN=channel_login,
                STATE=state_label,
                MESSAGE=disabled_reply.message_template or "",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )

        if action == "enable":
            if not existing_reply.disabled:
                return build_thread_result(
                    self.localizer,
                    "results.reply.already_enabled",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            enabled_reply = event_configuration.adapter_event_action_repository.set_action_disabled(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                disabled=False,
            )
            if enabled_reply is None:
                raise RuntimeError("Reply repository returned no row for enable adapter-event action.")
            return build_thread_result(
                self.localizer,
                "results.reply.enabled_event",
                thread=thread,
                DISPLAY_NAME=channel_display_name,
                LOGIN=channel_login,
                STATE=state_label,
                MESSAGE=enabled_reply.message_template or "",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )

        raise ValueError(self.localizer.text("results.reply.event_action_unsupported", language=thread.language))

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

    async def _display_index(self, thread_id: int, pattern_id: int) -> int | None:
        return await PatternDisplayIndexResolver(self.pattern_repository).resolve(
            thread_id=thread_id,
            pattern_id=pattern_id,
        )

    async def _resolve_thread(self, command: ReplyCommand) -> ThreadRecord | None:
        return await resolve_awaitable(self.thread_repository.get_by_discord_channel_id(command.discord_channel_id))
