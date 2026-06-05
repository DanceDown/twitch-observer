"""Business logic for Discord channel-management commands."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.database.connection import ChannelRepository, PatternRepository, ThreadRepository, UserPermissionRepository
from src.discord_results import build_thread_result, discord_user_mention
from src.errors import ApplicationInvariantError
from src.events.event_types import (
    AddTrackedChannelCommand,
    DiscordCommandResult,
    DiscordResultStyle,
    RemoveTrackedChannelCommand,
    SetTrackedChannelColorCommand,
)
from src.localization import Localizer
from src.normalization import normalize_optional_color
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.runtime_coordinator import TrackedChannelsChangedNotifier
from src.services.twitch_gateways import TwitchChannelLookup, TwitchIRCChannelGateway
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChannelCommandService:
    """Handle `/channel` add/remove requests from Discord."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchChannelLookup
    irc_gateway: TwitchIRCChannelGateway
    tracked_channels_notifier: TrackedChannelsChangedNotifier
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    permission_repository: UserPermissionRepository | None = None
    _guards: ThreadCommandGuards = field(init=False, repr=False)
    _runner: CommandExecutionRunner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=None,
            localizer=self.localizer,
            not_joined_key="results.channel.not_joined",
        )
        self._runner = CommandExecutionRunner(
            localizer=self.localizer,
            resolve_thread=lambda command: self.thread_repository.get_by_discord_channel_id(command.discord_channel_id),
            validation_error_key="results.channel.validation_error",
            twitch_api_error_key="results.channel.twitch_api_error",
            unexpected_error_key="results.channel.unexpected_error",
        )

    async def handle_add(self, command: AddTrackedChannelCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._add_channel(command), logger_=logger)

    async def handle_remove(self, command: RemoveTrackedChannelCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._remove_channel(command), logger_=logger)

    async def handle_color(self, command: SetTrackedChannelColorCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._set_color(command), logger_=logger)

    async def _require_manage_channels(self, command: object) -> tuple[object, DiscordCommandResult | None]:
        thread = await self._guards.require_permission(
            command,
            permission=ObserverPermission.MANAGE_CHANNELS,
            denial_key="results.channel.permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return None, thread
        return thread, None

    async def _resolve_channel(self, login: str):
        return await self.twitch_api.refresh_channel_by_login(login)

    async def _add_channel(self, command: AddTrackedChannelCommand) -> DiscordCommandResult:
        thread, denied = await self._require_manage_channels(command)
        if denied is not None:
            return denied

        twitch_user = await self._resolve_channel(command.twitch_channel_login)
        existing = await self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, twitch_user.user_id)
        if existing is not None:
            return build_thread_result(
                self.localizer,
                "results.channel.already_added",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )
        is_first_subscription = (
            await self.channel_repository.count_threads_by_twitch_channel_id(twitch_user.user_id) == 0
        )
        if is_first_subscription:
            await self.irc_gateway.ensure_connected()
            await self.irc_gateway.join_channel(twitch_user.login)
        await self.channel_repository.add_channel(thread.thread_id, twitch_user.user_id)
        logger.debug(
            "Added tracked channel thread_id=%s twitch_channel_id=%s twitch_login=%s",
            thread.thread_id,
            twitch_user.user_id,
            twitch_user.login,
        )
        await self._notify_tracked_channels_changed()
        return build_thread_result(
            self.localizer,
            "results.channel.added",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            DISPLAY_NAME=twitch_user.display_name,
            LOGIN=twitch_user.login,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    async def _set_color(self, command: SetTrackedChannelColorCommand) -> DiscordCommandResult:
        thread, denied = await self._require_manage_channels(command)
        if denied is not None:
            return denied

        twitch_user = await self._resolve_channel(command.twitch_channel_login)
        existing = await self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, twitch_user.user_id)
        if existing is None:
            return build_thread_result(
                self.localizer,
                "results.channel.not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )

        normalized_color = normalize_optional_color(command.color)
        if normalized_color is None:
            updated = await self.channel_repository.set_color(
                    thread_id=thread.thread_id,
                    twitch_channel_id=twitch_user.user_id,
                    color=None,
                )
            
            if updated is None:
                raise ApplicationInvariantError("Tracked channel color clear returned no row.")
            return build_thread_result(
                self.localizer,
                "results.channel.color_cleared",
                thread=thread,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
                USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
            )
        updated = await self.channel_repository.set_color(
                thread_id=thread.thread_id,
                twitch_channel_id=twitch_user.user_id,
                color=normalized_color,
            )
        
        if updated is None:
            raise ApplicationInvariantError("Tracked channel color update returned no row.")
        return build_thread_result(
            self.localizer,
            "results.channel.color_updated",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            DISPLAY_NAME=twitch_user.display_name,
            LOGIN=twitch_user.login,
            COLOR=updated.color or "",
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    async def _remove_channel(self, command: RemoveTrackedChannelCommand) -> DiscordCommandResult:
        thread, denied = await self._require_manage_channels(command)
        if denied is not None:
            return denied

        twitch_user = await self._resolve_channel(command.twitch_channel_login)
        existing = await self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, twitch_user.user_id)
        if existing is None:
            return build_thread_result(
                self.localizer,
                "results.channel.not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )

        if (
            await self.pattern_repository.count_channel_scope_references(
                    thread_id=thread.thread_id,
                    twitch_channel_id=twitch_user.user_id,
                )
            
            > 0
        ):
            return build_thread_result(
                self.localizer,
                "results.channel.in_use",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )

        is_last_subscription = await self.channel_repository.count_threads_by_twitch_channel_id(twitch_user.user_id) == 1
        if is_last_subscription:
            await self.irc_gateway.ensure_connected()
            await self.irc_gateway.leave_channel(twitch_user.login)
        await self.channel_repository.remove_channel(thread.thread_id, twitch_user.user_id)
        logger.debug(
            "Removed tracked channel thread_id=%s twitch_channel_id=%s twitch_login=%s",
            thread.thread_id,
            twitch_user.user_id,
            twitch_user.login,
        )
        await self._notify_tracked_channels_changed()
        return build_thread_result(
            self.localizer,
            "results.channel.removed",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            DISPLAY_NAME=twitch_user.display_name,
            LOGIN=twitch_user.login,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    async def _notify_tracked_channels_changed(self) -> None:
        await self.tracked_channels_notifier.notify_tracked_channels_changed()
