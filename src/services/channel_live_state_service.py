"""Tracked Twitch channel events, persistence and Discord notifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRepository,
    ThreadRecord,
    ThreadRepository,
    UserPermissionRepository,
)
from src.discord_results import build_thread_result
from src.events.commands import AddChannelEventCommand, RemoveChannelEventCommand, SetChannelEventColorCommand
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.normalization import normalize_optional_color
from src.services.channel_event_display_index import ChannelEventDisplayIndexResolver
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.twitch_gateways import TwitchChannelStateLookup
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    DISCORD_NOTIFY_ACTION,
    STREAM_OFFLINE_EVENT_KEY,
    STREAM_ONLINE_EVENT_KEY,
    TWITCH_ADAPTER_KEY,
)
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)

ChannelEventCommand = AddChannelEventCommand | RemoveChannelEventCommand | SetChannelEventColorCommand


@dataclass(slots=True, frozen=True)
class _ChannelEventPermissionCommand:
    discord_channel_id: int
    requester_id: int


@dataclass(slots=True)
class ChannelEventCommandService:
    """Handle live/offline notification command configuration."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    twitch_api: TwitchChannelStateLookup
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    _runner: CommandExecutionRunner = field(init=False, repr=False)
    _guards: ThreadCommandGuards = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._runner = CommandExecutionRunner(
            localizer=self.localizer,
            resolve_thread=self._resolve_thread,
            validation_error_key="results.channel_event.validation_error",
            twitch_api_error_key="results.channel_event.twitch_api_error",
            unexpected_error_key="results.channel_event.unexpected_error",
        )
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=None,
            localizer=self.localizer,
            not_joined_key="results.channel_event.not_joined",
        )

    async def handle_add_command(self, command: AddChannelEventCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._handle_action(command, action="add"), logger_=logger)

    async def handle_remove_command(self, command: RemoveChannelEventCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._handle_action(command, action="remove"), logger_=logger)

    async def handle_set_color_command(self, command: SetChannelEventColorCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._set_color(command), logger_=logger)

    async def _handle_action(self, command: ChannelEventCommand, *, action: str) -> DiscordCommandResult:
        thread = await self._ensure_permission(command)
        if isinstance(thread, DiscordCommandResult):
            return thread

        tracked_channel = await self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, command.twitch_channel_id)
        
        if tracked_channel is None:
            return build_thread_result(
                self.localizer,
                "results.channel_event.channel_not_tracked",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        event_key = command.event_kind.value
        if event_key not in {STREAM_ONLINE_EVENT_KEY, STREAM_OFFLINE_EVENT_KEY}:
            raise ValueError(self.localizer.text("results.channel_event.unsupported_event", language=thread.language))

        channel_display_name, channel_login = await self._channel_identity(command.twitch_channel_id)
        if action == "add":
            return await self._add_notification(command, thread, channel_display_name, channel_login)
        if action == "remove":
            return await self._update_notification(
                command,
                action=action,
                thread=thread,
                channel_display_name=channel_display_name,
                channel_login=channel_login,
            )
        raise ValueError(self.localizer.text("results.channel_event.unsupported_action", language=thread.language))

    async def _add_notification(
        self,
        command: ChannelEventCommand,
        thread: ThreadRecord,
        channel_display_name: str,
        channel_login: str,
    ) -> DiscordCommandResult:
        adapter_event = await self.adapter_event_repository.upsert_event(
                thread_id=thread.thread_id,
                adapter_key=TWITCH_ADAPTER_KEY,
                subject_type=CHANNEL_SUBJECT_TYPE,
                subject_id=command.twitch_channel_id,
                event_key=command.event_kind.value,
            )
        
        existing_action = await self.adapter_event_action_repository.get_action(
                event_id=adapter_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
            )
        
        action = await self.adapter_event_action_repository.upsert_action(
                event_id=adapter_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
                message_template=None,
                reply_as_reply=False,
            )
        
        if existing_action is None:
            key = "results.channel_event.notification_added"
            style = DiscordResultStyle.SUCCESS
            ephemeral = False
        elif existing_action.disabled:
            key = "results.channel_event.notification_enabled"
            style = DiscordResultStyle.SUCCESS
            ephemeral = False
        else:
            key = "results.channel_event.already_configured"
            style = DiscordResultStyle.INFO
            ephemeral = True
        logger.debug(
            "Configured tracked channel event thread_id=%s event_id=%s action=%s event_key=%s",
            thread.thread_id,
            adapter_event.event_id,
            action.action_type,
            adapter_event.event_key,
        )
        display_id = await self._display_index(thread.thread_id, adapter_event.event_id) or adapter_event.event_id
        return build_thread_result(
            self.localizer,
            key,
            thread=thread,
            style=style,
            ephemeral=ephemeral,
            sources={
                "view": self._event_view(
                    requester_id=command.requester_id,
                    display_id=display_id,
                    state=self._state_label(command.event_kind.value, thread),
                    channel_display_name=channel_display_name,
                    channel_login=channel_login,
                )
            },
        )

    async def _update_notification(
        self,
        command: ChannelEventCommand,
        *,
        action: str,
        thread: ThreadRecord,
        channel_display_name: str,
        channel_login: str,
    ) -> DiscordCommandResult:
        adapter_event = await self.adapter_event_repository.get_event(
                thread_id=thread.thread_id,
                adapter_key=TWITCH_ADAPTER_KEY,
                subject_type=CHANNEL_SUBJECT_TYPE,
                subject_id=command.twitch_channel_id,
                event_key=command.event_kind.value,
            )
        
        existing_action = (
            None
            if adapter_event is None
            else await self.adapter_event_action_repository.get_action(
                    event_id=adapter_event.event_id,
                    action_type=DISCORD_NOTIFY_ACTION,
                )
            
        )
        if adapter_event is None or existing_action is None:
            return build_thread_result(
                self.localizer,
                "results.channel_event.none_configured",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                sources={
                    "view": self._event_view(
                        state=self._state_label(command.event_kind.value, thread),
                        channel_display_name=channel_display_name,
                        channel_login=channel_login,
                    )
                },
            )

        display_id = await self._display_index(thread.thread_id, adapter_event.event_id) or adapter_event.event_id
        await self.adapter_event_action_repository.remove_action(
                event_id=adapter_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
            )
        
        key = "results.channel_event.notification_removed"

        return build_thread_result(
            self.localizer,
            key,
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": self._event_view(
                    requester_id=command.requester_id,
                    display_id=display_id,
                    state=self._state_label(command.event_kind.value, thread),
                    channel_display_name=channel_display_name,
                    channel_login=channel_login,
                )
            },
        )

    async def _channel_identity(self, twitch_channel_id: str) -> tuple[str, str]:
        cached = self.twitch_api.get_cached_user_by_id(twitch_channel_id.strip())
        twitch_user = cached if cached is not None else await self.twitch_api.get_channel_by_id(twitch_channel_id)
        return twitch_user.display_name, twitch_user.login

    def _state_label(self, event_key: str, thread: ThreadRecord) -> str:
        state_key = "live" if event_key == STREAM_ONLINE_EVENT_KEY else "offline"
        return self.localizer.text(f"results.channel_event.state.{state_key}", language=thread.language)

    async def _set_color(self, command: SetChannelEventColorCommand) -> DiscordCommandResult:
        thread = await self._ensure_permission(command)
        if isinstance(thread, DiscordCommandResult):
            return thread

        tracked_channel = await self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, command.twitch_channel_id)
        
        if tracked_channel is None:
            return build_thread_result(
                self.localizer,
                "results.channel_event.channel_not_tracked",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        adapter_event = await self.adapter_event_repository.get_event(
                thread_id=thread.thread_id,
                adapter_key=TWITCH_ADAPTER_KEY,
                subject_type=CHANNEL_SUBJECT_TYPE,
                subject_id=command.twitch_channel_id,
                event_key=command.event_kind.value,
            )
        
        notify_action = (
            None
            if adapter_event is None
            else await self.adapter_event_action_repository.get_action(
                    event_id=adapter_event.event_id,
                    action_type=DISCORD_NOTIFY_ACTION,
                )
            
        )
        channel_display_name, channel_login = await self._channel_identity(command.twitch_channel_id)
        if adapter_event is None or notify_action is None:
            return build_thread_result(
                self.localizer,
                "results.channel_event.none_configured",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                sources={
                    "view": self._event_view(
                        state=self._state_label(command.event_kind.value, thread),
                        channel_display_name=channel_display_name,
                        channel_login=channel_login,
                    )
                },
            )

        display_id = await self._display_index(thread.thread_id, adapter_event.event_id) or adapter_event.event_id
        try:
            normalized_color = normalize_optional_color(command.color)
        except ValueError as error:
            raise ValueError(self.localizer.text("results.channel_event.invalid_color", language=thread.language)) from error

        if normalized_color is None:
            updated = await self.adapter_event_action_repository.set_action_color(
                    event_id=adapter_event.event_id,
                    action_type=DISCORD_NOTIFY_ACTION,
                    color=None,
                )
            
            if updated is None:
                raise RuntimeError("Adapter event action repository returned no row for clear color.")
            return build_thread_result(
                self.localizer,
                "results.channel_event.color_cleared",
                thread=thread,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                sources={
                    "view": self._event_view(
                        requester_id=command.requester_id,
                        display_id=display_id,
                        state=self._state_label(command.event_kind.value, thread),
                        channel_display_name=channel_display_name,
                        channel_login=channel_login,
                    )
                },
            )

        if notify_action.color == normalized_color:
            return build_thread_result(
                self.localizer,
                "results.channel_event.already_color",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                sources={
                    "view": self._event_view(
                        display_id=display_id,
                        state=self._state_label(command.event_kind.value, thread),
                        channel_display_name=channel_display_name,
                        channel_login=channel_login,
                        color=normalized_color,
                    )
                },
            )

        updated = await self.adapter_event_action_repository.set_action_color(
                event_id=adapter_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
                color=normalized_color,
            )
        
        if updated is None:
            raise RuntimeError("Adapter event action repository returned no row for set color.")
        return build_thread_result(
            self.localizer,
            "results.channel_event.color_updated",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": self._event_view(
                    requester_id=command.requester_id,
                    display_id=display_id,
                    state=self._state_label(command.event_kind.value, thread),
                    channel_display_name=channel_display_name,
                    channel_login=channel_login,
                    color=updated.color or "",
                )
            },
        )

    async def _ensure_permission(
        self,
        command: ChannelEventCommand,
    ) -> ThreadRecord | DiscordCommandResult:
        return await self._guards.require_permission(
            _ChannelEventPermissionCommand(
                discord_channel_id=command.discord_channel_id,
                requester_id=command.requester_id,
            ),
            permission=ObserverPermission.MANAGE_CHANNELS,
            denial_key="results.channel_event.permission_denied",
        )

    async def _resolve_thread(self, command: ChannelEventCommand) -> ThreadRecord | None:
        return await self.thread_repository.get_by_discord_channel_id(command.discord_channel_id)

    async def _display_index(self, thread_id: int, event_id: int) -> int | None:
        return await ChannelEventDisplayIndexResolver(self.adapter_event_action_repository).resolve(
            thread_id=thread_id,
            event_id=event_id,
        )

    @staticmethod
    def _event_view(
        *,
        state: str,
        channel_display_name: str,
        channel_login: str,
        requester_id: int | None = None,
        display_id: int | None = None,
        color: str | None = None,
    ) -> dict[str, object]:
        view: dict[str, object] = {
            "state": state,
            "channel": {
                "display_name": channel_display_name,
                "login": channel_login,
            },
        }
        if requester_id is not None:
            view["requester_id"] = requester_id
        if display_id is not None:
            view["display_id"] = display_id
        if color is not None:
            view["color"] = color
        return view
