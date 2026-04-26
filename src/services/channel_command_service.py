from __future__ import annotations

"""Business logic for Discord channel-management commands."""

import logging
import re
from dataclasses import dataclass, field

from src.adapters.twitch_api import (
    TwitchAPIClient,
    TwitchAPIConfigurationError,
    TwitchAPIError,
    TwitchChannelNotFoundError,
)
from src.database.connection import ChannelRepository, PatternRepository, ThreadRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordChannelRequestedEvent,
    DiscordCommandResult,
    DiscordResultStyle,
    EventType,
    TwitchTrackedChannelsChangedEvent,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


class IRCChannelManager:
    """Interface for the IRC adapter actions used by the service."""

    async def join_channel(self, channel_login: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def leave_channel(self, channel_login: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(slots=True)
class ChannelCommandService:
    """Handle `/channel` add/remove requests from Discord."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchAPIClient
    irc_manager: IRCChannelManager
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_CHANNEL_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordChannelRequestedEvent) -> None:
        """Apply the requested add/remove action and complete the result future."""
        try:
            result = await self._handle_action(event)
        except (TwitchAPIConfigurationError, TwitchChannelNotFoundError) as error:
            thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
            result = self.localizer.thread_result(
                "results.validation_error",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
            )
        except TwitchAPIError as error:
            thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
            result = self.localizer.thread_result(
                "results.twitch_api_error",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
            )
        except Exception as error:
            logger.exception("Unexpected error while handling channel command.")
            thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
            result = self.localizer.thread_result(
                "results.unexpected_error",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_action(self, event: DiscordChannelRequestedEvent) -> DiscordCommandResult:
        logger.debug(
            "Handling channel action discord_channel_id=%s requester_id=%s action=%s twitch_channel_login=%s",
            event.discord_channel_id,
            event.requester_id,
            event.action,
            event.twitch_channel_login,
        )
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if thread is None:
            return self.localizer.result(
                "results.not_joined",
                language=self.localizer.default_language,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=event.requester_id,
            permission_repository=self.permission_repository,
            required_permission=ObserverPermission.MANAGE_CHANNELS,
        ):
            return self.localizer.thread_result(
                "results.channel.permission_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        refresh_lookup = getattr(self.twitch_api, "refresh_user_by_login", self.twitch_api.get_user_by_login)
        twitch_user = await refresh_lookup(event.twitch_channel_login)
        existing = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, twitch_user.user_id)
        if event.action == "add":
            if existing is not None:
                return self.localizer.thread_result(
                    "results.channel.already_added",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                    DISPLAY_NAME=twitch_user.display_name,
                    LOGIN=twitch_user.login,
                )
            self.channel_repository.add_channel(thread.thread_id, twitch_user.user_id)
            logger.debug(
                "Added tracked channel thread_id=%s twitch_channel_id=%s twitch_login=%s",
                thread.thread_id,
                twitch_user.user_id,
                twitch_user.login,
            )
            if self.channel_repository.count_threads_by_twitch_channel_id(twitch_user.user_id) == 1:
                await self.irc_manager.join_channel(twitch_user.login)
            await self.event_bus.publish(
                EventType.TWITCH_TRACKED_CHANNELS_CHANGED,
                TwitchTrackedChannelsChangedEvent(reason="channel_added"),
            )
            return self.localizer.thread_result(
                "results.channel.added",
                thread=thread,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )

        if event.action == "color":
            if existing is None:
                return self.localizer.thread_result(
                    "results.channel.not_found",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                    DISPLAY_NAME=twitch_user.display_name,
                    LOGIN=twitch_user.login,
                )
            if event.clear_color:
                updated = self.channel_repository.set_color(
                    thread_id=thread.thread_id,
                    twitch_channel_id=twitch_user.user_id,
                    color=None,
                )
                assert updated is not None
                return self.localizer.thread_result(
                    "results.channel.color_cleared",
                    thread=thread,
                    style=DiscordResultStyle.SUCCESS,
                    ephemeral=False,
                    DISPLAY_NAME=twitch_user.display_name,
                    LOGIN=twitch_user.login,
                )
            if event.color is None or not re.fullmatch(r"#[0-9A-Fa-f]{6}", event.color.strip()):
                return self.localizer.thread_result(
                    "results.validation_error",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                    DETAIL="Color must use the format `#RRGGBB` or be empty.",
                )
            updated = self.channel_repository.set_color(
                thread_id=thread.thread_id,
                twitch_channel_id=twitch_user.user_id,
                color=event.color.strip(),
            )
            assert updated is not None
            return self.localizer.thread_result(
                "results.channel.color_updated",
                thread=thread,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
                COLOR=updated.color or "",
            )

        if event.action != "remove":
            return self.localizer.thread_result(
                "results.channel.unsupported_action",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if existing is None:
            return self.localizer.thread_result(
                "results.channel.not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )

        if self.pattern_repository.count_channel_scope_references(
            thread_id=thread.thread_id,
            twitch_channel_id=twitch_user.user_id,
        ) > 0:
            return self.localizer.thread_result(
                "results.channel.in_use",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )

        self.channel_repository.remove_channel(thread.thread_id, twitch_user.user_id)
        logger.debug(
            "Removed tracked channel thread_id=%s twitch_channel_id=%s twitch_login=%s",
            thread.thread_id,
            twitch_user.user_id,
            twitch_user.login,
        )
        if self.channel_repository.count_threads_by_twitch_channel_id(twitch_user.user_id) == 0:
            await self.irc_manager.leave_channel(twitch_user.login)
        await self.event_bus.publish(
            EventType.TWITCH_TRACKED_CHANNELS_CHANGED,
            TwitchTrackedChannelsChangedEvent(reason="channel_removed"),
        )
        return self.localizer.thread_result(
            "results.channel.removed",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            DISPLAY_NAME=twitch_user.display_name,
            LOGIN=twitch_user.login,
        )
