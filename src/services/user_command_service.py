from __future__ import annotations

"""Business logic for tracked Twitch-user management commands."""

import logging
from dataclasses import dataclass, field

from src.adapters.twitch_api import (
    TwitchAPIClient,
    TwitchAPIConfigurationError,
    TwitchAPIError,
    TwitchChannelNotFoundError,
)
from src.database.connection import ThreadRepository, TrackedUserRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    DiscordUserRequestedEvent,
    EventType,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserCommandService:
    """Handle tracked Twitch-user add/remove requests from Discord."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    tracked_user_repository: TrackedUserRepository
    twitch_api: TwitchAPIClient
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_USER_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordUserRequestedEvent) -> None:
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
            logger.exception("Unexpected error while handling tracked-user command.")
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

    async def _handle_action(self, event: DiscordUserRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.MANAGE_PATTERNS,
        ):
            return self.localizer.thread_result(
                "results.user.permission_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        refresh_lookup = getattr(self.twitch_api, "refresh_user_by_login", self.twitch_api.get_user_by_login)
        twitch_user = await refresh_lookup(event.twitch_user_login)
        existing = self.tracked_user_repository.get_by_thread_and_twitch_user(thread.thread_id, twitch_user.user_id)

        if event.action == "add":
            if existing is not None:
                return self.localizer.thread_result(
                    "results.user.already_added",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                    DISPLAY_NAME=twitch_user.display_name,
                )
            self.tracked_user_repository.add_user(thread.thread_id, twitch_user.user_id)
            return self.localizer.thread_result(
                "results.user.added",
                thread=thread,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                DISPLAY_NAME=twitch_user.display_name,
                LOGIN=twitch_user.login,
            )

        if event.action != "remove":
            return self.localizer.thread_result(
                "results.user.unsupported_action",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if existing is None:
            return self.localizer.thread_result(
                "results.user.not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
            )

        if (
            self.tracked_user_repository.count_pattern_scope_references(
                thread_id=thread.thread_id,
                twitch_user_id=twitch_user.user_id,
            )
            > 0
        ):
            return self.localizer.thread_result(
                "results.user.in_use",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DISPLAY_NAME=twitch_user.display_name,
            )

        self.tracked_user_repository.remove_user(thread.thread_id, twitch_user.user_id)
        return self.localizer.thread_result(
            "results.user.removed",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            DISPLAY_NAME=twitch_user.display_name,
        )
