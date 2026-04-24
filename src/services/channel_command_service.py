from __future__ import annotations

"""Business logic for Discord channel-management commands."""

from dataclasses import dataclass
import logging
import re

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
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_CHANNEL_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordChannelRequestedEvent) -> None:
        """Apply the requested add/remove action and complete the result future."""
        try:
            result = await self._handle_action(event)
        except (TwitchAPIConfigurationError, TwitchChannelNotFoundError) as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except TwitchAPIError as error:
            result = DiscordCommandResult(
                title="Twitch API Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling channel command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
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
            return DiscordCommandResult(
                title="Not Joined",
                message="This Discord channel is not connected yet. Use `/join` first.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=event.requester_id,
            permission_repository=self.permission_repository,
            required_permission=ObserverPermission.MANAGE_CHANNELS,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message="You do not have permission to change tracked Twitch channels.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        refresh_lookup = getattr(self.twitch_api, "refresh_user_by_login", self.twitch_api.get_user_by_login)
        twitch_user = await refresh_lookup(event.twitch_channel_login)
        existing = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, twitch_user.user_id)
        if event.action == "add":
            if existing is not None:
                return DiscordCommandResult(
                    title="Already Added",
                    message=(
                        f"Twitch channel `{twitch_user.display_name}` (`{twitch_user.login}`) "
                        "is already tracked."
                    ),
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
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
            return DiscordCommandResult(
                title="Channel Added",
                message=(
                    f"Added Twitch channel `{twitch_user.display_name}` (`{twitch_user.login}`)"
                ),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "color":
            if existing is None:
                return DiscordCommandResult(
                    title="Not Found",
                    message=(
                        f"Twitch channel `{twitch_user.display_name}` (`{twitch_user.login}`) "
                        "is not currently tracked."
                    ),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            if event.clear_color:
                updated = self.channel_repository.set_color(
                    thread_id=thread.thread_id,
                    twitch_channel_id=twitch_user.user_id,
                    color=None,
                )
                assert updated is not None
                return DiscordCommandResult(
                    title="Channel Color Cleared",
                    message=(
                        f"Cleared the custom color for Twitch channel `{twitch_user.display_name}` "
                        f"(`{twitch_user.login}`)."
                    ),
                    style=DiscordResultStyle.SUCCESS,
                    ephemeral=False,
                )
            if event.color is None or not re.fullmatch(r"#[0-9A-Fa-f]{6}", event.color.strip()):
                return DiscordCommandResult(
                    title="Validation Error",
                    message="Color must use the format `#RRGGBB` or be empty.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            updated = self.channel_repository.set_color(
                thread_id=thread.thread_id,
                twitch_channel_id=twitch_user.user_id,
                color=event.color.strip(),
            )
            assert updated is not None
            return DiscordCommandResult(
                title="Channel Color Updated",
                message=(
                    f"Set the color for Twitch channel `{twitch_user.display_name}` (`{twitch_user.login}`) "
                    f"to `{updated.color}`."
                ),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action != "remove":
            return DiscordCommandResult(
                title="Validation Error",
                message="Unsupported action. Use `add`, `remove`, or `color`.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if existing is None:
            return DiscordCommandResult(
                title="Not Found",
                message=(
                    f"Twitch channel `{twitch_user.display_name}` (`{twitch_user.login}`) "
                    "is not currently tracked."
                ),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if self.pattern_repository.count_channel_scope_references(
            thread_id=thread.thread_id,
            twitch_channel_id=twitch_user.user_id,
        ) > 0:
            return DiscordCommandResult(
                title="Channel In Use",
                message=(
                    f"Twitch channel `{twitch_user.display_name}` (`{twitch_user.login}`) "
                    "is still referenced by one or more pings."
                ),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
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
        return DiscordCommandResult(
            title="Channel Removed",
            message=(
                f"Removed Twitch channel `{twitch_user.display_name}` (`{twitch_user.login}`)"
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )
