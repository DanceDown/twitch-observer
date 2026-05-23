"""Business logic for explicitly joining and leaving Discord contexts."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.gateways.twitch_api import TwitchAPIError
from src.database.connection import ChannelRepository, ThreadRepository, UserPermissionRepository
from src.discord_results import build_result, build_thread_result, discord_user_mention
from src.errors import ApplicationInvariantError
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    JoinThreadCommand,
    LeaveThreadCommand,
    SetThreadColorCommand,
    SetThreadEnabledCommand,
    SetThreadLanguageCommand,
)
from src.localization import Localizer
from src.normalization import normalize_language, normalize_optional_color
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.runtime_coordinator import TrackedChannelsChangedNotifier
from src.services.twitch_gateways import TwitchDirectoryGateway, TwitchIRCChannelGateway
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ThreadLifecycleService:
    """Handle `/join` and `/leave` for one Discord channel or DM context."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    twitch_api: TwitchDirectoryGateway
    irc_gateway: TwitchIRCChannelGateway
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    permission_repository: UserPermissionRepository | None = None
    tracked_channels_notifier: TrackedChannelsChangedNotifier | None = None
    _guards: ThreadCommandGuards = field(init=False, repr=False)
    _runner: CommandExecutionRunner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=None,
            localizer=self.localizer,
        )
        self._runner = CommandExecutionRunner(
            localizer=self.localizer,
            resolve_thread=lambda command: self.thread_repository.get_by_discord_channel_id(command.discord_channel_id),
        )

    async def handle_join(self, command: JoinThreadCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._join_context(command), logger_=logger)

    async def handle_leave(self, command: LeaveThreadCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._leave_context(command), logger_=logger)

    async def handle_set_enabled(self, command: SetThreadEnabledCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._set_context_enabled(command), logger_=logger)

    async def handle_set_color(self, command: SetThreadColorCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._set_context_color(command), logger_=logger)

    async def handle_set_language(self, command: SetThreadLanguageCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._set_context_language(command), logger_=logger)

    async def _join_context(self, command: JoinThreadCommand) -> DiscordCommandResult:
        existing = self.thread_repository.get_by_discord_channel_id(command.discord_channel_id)
        if existing is not None:
            if existing.owner_id == command.requester_id:
                return build_thread_result(
                    self.localizer,
                    "results.thread.already_joined",
                    thread=existing,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            return build_thread_result(
                self.localizer,
                "results.thread.already_joined_other_owner",
                thread=existing,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        created = self.thread_repository.create(
            owner_id=command.requester_id,
            discord_channel_id=command.discord_channel_id,
        )
        logger.debug(
            "Joined Discord context discord_channel_id=%s owner_id=%s",
            command.discord_channel_id,
            command.requester_id,
        )
        return build_thread_result(
            self.localizer,
            "results.thread.joined",
            thread=created,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            USER=discord_user_mention(self.localizer, command.requester_id, language=created.language),
        )

    async def _leave_context(self, command: LeaveThreadCommand) -> DiscordCommandResult:
        thread = self._guards.require_permission(
            command,
            permission=ObserverPermission.LEAVE_CONTEXT,
            denial_key="results.thread.leave_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        removed_channel_ids = sorted(
            {channel.twitch_channel_id for channel in self.channel_repository.list_channels_for_thread(thread.thread_id)}
        )
        part_candidate_channel_ids: list[str] = []
        for twitch_channel_id in removed_channel_ids:
            remaining_thread_ids = set(self.channel_repository.list_thread_ids_by_twitch_channel_id(twitch_channel_id))
            remaining_thread_ids.discard(thread.thread_id)
            if not remaining_thread_ids:
                part_candidate_channel_ids.append(twitch_channel_id)

        deleted = self.thread_repository.delete_by_discord_channel_id(command.discord_channel_id)
        if deleted is None:
            return build_result(
                self.localizer,
                "results.not_joined",
                language=self.localizer.default_language,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        for twitch_channel_id in part_candidate_channel_ids:
            try:
                cached = self.twitch_api.get_cached_user_by_id(twitch_channel_id.strip())
                if cached is not None:
                    twitch_user = cached
                else:
                    twitch_user = await self.twitch_api.get_channel_by_id(twitch_channel_id)
            except TwitchAPIError:
                logger.warning(
                    "Could not resolve Twitch channel id=%s while leaving discord_channel_id=%s; skipping IRC PART.",
                    twitch_channel_id,
                    command.discord_channel_id,
                )
            else:
                await self.irc_gateway.leave_channel(twitch_user.login)

        logger.debug(
            "Left Discord context discord_channel_id=%s owner_id=%s removed_twitch_channels=%s",
            command.discord_channel_id,
            command.requester_id,
            removed_channel_ids,
        )
        await self._notify_tracked_channels_changed()
        return build_thread_result(
            self.localizer,
            "results.thread.left",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    def _set_context_enabled(self, command: SetThreadEnabledCommand) -> DiscordCommandResult:
        thread = self._guards.require_permission(
            command,
            permission=ObserverPermission.CONTROL_OBSERVER,
            denial_key="results.thread.enable_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread
        if thread.enabled == command.enabled:
            return build_thread_result(
                self.localizer,
                "results.thread.already_on" if command.enabled else "results.thread.already_off",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.thread_repository.set_enabled(
            discord_channel_id=command.discord_channel_id,
            enabled=command.enabled,
        )
        if updated is None:
            raise ApplicationInvariantError("Thread enable state update returned no row.")
        return build_thread_result(
            self.localizer,
            "results.thread.enabled" if command.enabled else "results.thread.disabled",
            thread=updated,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            USER=discord_user_mention(self.localizer, command.requester_id, language=updated.language),
        )

    def _set_context_color(self, command: SetThreadColorCommand) -> DiscordCommandResult:
        thread = self._guards.require_permission(
            command,
            permission=ObserverPermission.CONTROL_OBSERVER,
            denial_key="results.thread.color_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        normalized_color = normalize_optional_color(command.color)
        if normalized_color is None:
            updated = self.thread_repository.set_color(discord_channel_id=command.discord_channel_id, color=None)
            if updated is None:
                raise ApplicationInvariantError("Thread color clear returned no row.")
            return build_thread_result(
                self.localizer,
                "results.thread.color_cleared",
                thread=updated,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                USER=discord_user_mention(self.localizer, command.requester_id, language=updated.language),
            )
        if thread.color == normalized_color:
            return build_thread_result(
                self.localizer,
                "results.thread.already_color",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                COLOR=normalized_color,
            )
        updated = self.thread_repository.set_color(
            discord_channel_id=command.discord_channel_id,
            color=normalized_color,
        )
        if updated is None:
            raise ApplicationInvariantError("Thread color update returned no row.")
        return build_thread_result(
            self.localizer,
            "results.thread.color_updated",
            thread=updated,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            COLOR=updated.color or "",
            USER=discord_user_mention(self.localizer, command.requester_id, language=updated.language),
        )

    def _set_context_language(self, command: SetThreadLanguageCommand) -> DiscordCommandResult:
        thread = self._guards.require_permission(
            command,
            permission=ObserverPermission.CONTROL_OBSERVER,
            denial_key="results.thread.language_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        requested_language = normalize_language(command.language)
        if not self.localizer.has_language(requested_language):
            return build_thread_result(
                self.localizer,
                "results.validation_error",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=self.localizer.text(
                    "results.validation_detail.unsupported_language",
                    language=thread.language,
                    LANGUAGES=self.localizer.available_languages(),
                ),
            )
        if thread.language == requested_language:
            language_name = self.localizer.text("common.language_name", language=requested_language)
            return build_thread_result(
                self.localizer,
                "results.thread.already_language",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                LANGUAGE_NAME=language_name,
                LANGUAGE_CODE=requested_language,
            )
        updated = self.thread_repository.set_language(
            discord_channel_id=command.discord_channel_id,
            language=requested_language,
        )
        if updated is None:
            raise ApplicationInvariantError("Thread language update returned no row.")
        language_name = self.localizer.text("common.language_name", language=requested_language)
        return build_thread_result(
            self.localizer,
            "results.thread.language_updated",
            thread=updated,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            LANGUAGE_NAME=language_name,
            LANGUAGE_CODE=requested_language,
            USER=discord_user_mention(self.localizer, command.requester_id, language=updated.language),
        )

    async def _notify_tracked_channels_changed(self) -> None:
        if self.tracked_channels_notifier is None:
            return
        await self.tracked_channels_notifier.notify_tracked_channels_changed()
