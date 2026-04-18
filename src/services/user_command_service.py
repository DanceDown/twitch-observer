from __future__ import annotations

"""Business logic for tracked Twitch-user management commands."""

from dataclasses import dataclass
import logging

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
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_USER_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordUserRequestedEvent) -> None:
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
            logger.exception("Unexpected error while handling tracked-user command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_action(self, event: DiscordUserRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.MANAGE_PATTERNS,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message="You do not have permission to change tracked Twitch users in this Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        twitch_user = await self.twitch_api.get_user_by_login(event.twitch_user_login)
        existing = self.tracked_user_repository.get_by_thread_and_twitch_user(thread.thread_id, twitch_user.user_id)

        if event.action == "add":
            if existing is not None:
                return DiscordCommandResult(
                    title="Already Added",
                    message=f"{twitch_user.display_name} is already in the tracked Twitch-user list.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            self.tracked_user_repository.add_user(thread.thread_id, twitch_user.user_id)
            return DiscordCommandResult(
                title="Tracked User Added",
                message=f"Added [{twitch_user.display_name}](https://www.twitch.tv/{twitch_user.login}) to the tracked Twitch-user list.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action != "remove":
            return DiscordCommandResult(
                title="Validation Error",
                message="Unsupported action. Use `add` or `remove`.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if existing is None:
            return DiscordCommandResult(
                title="Not Found",
                message=f"{twitch_user.display_name} is not in the tracked Twitch-user list.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if self.tracked_user_repository.count_pattern_scope_references(
            thread_id=thread.thread_id,
            twitch_user_id=twitch_user.user_id,
        ) > 0:
            return DiscordCommandResult(
                title="User In Use",
                message=f"{twitch_user.display_name} is still referenced by one or more pings.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        self.tracked_user_repository.remove_user(thread.thread_id, twitch_user.user_id)
        return DiscordCommandResult(
            title="Tracked User Removed",
            message=f"Removed {twitch_user.display_name} from the tracked Twitch-user list.",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )
