from __future__ import annotations

"""Manual and adapter-driven tracked-channel live state handling."""

from dataclasses import dataclass
import logging

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError
from src.database.connection import ChannelRepository, ThreadRecord, ThreadRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordChannelLiveStateRequestedEvent,
    DiscordCommandResult,
    DiscordResultStyle,
    EventType,
    TwitchChannelLiveStateChangedEvent,
)
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChannelLiveStateCommandService:
    """Handle `/live` and `/offline` requests from Discord."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    twitch_api: TwitchAPIClient
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_CHANNEL_LIVE_STATE_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordChannelLiveStateRequestedEvent) -> None:
        try:
            result = await self._handle_change(event)
        except TwitchAPIError as error:
            result = DiscordCommandResult(
                title="Twitch API Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling live-state command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_change(self, event: DiscordChannelLiveStateRequestedEvent) -> DiscordCommandResult:
        thread = self._ensure_permission(event)
        if isinstance(thread, DiscordCommandResult):
            return thread

        tracked_channel = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, event.twitch_channel_id)
        if tracked_channel is None:
            return DiscordCommandResult(
                title="Channel Not Tracked",
                message="This Twitch channel is not tracked in the current Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        twitch_channel = await self.twitch_api.get_user_by_id(event.twitch_channel_id)
        change_event = TwitchChannelLiveStateChangedEvent(
            twitch_channel_id=event.twitch_channel_id,
            twitch_channel_login=twitch_channel.login,
            is_live=event.is_live,
        )
        await self.event_bus.publish(EventType.TWITCH_CHANNEL_LIVE_STATE_CHANGED, change_event)
        state_label = "live" if event.is_live else "offline"
        return DiscordCommandResult(
            title=f"Channel Marked {state_label.capitalize()}",
            message=(
                f"Marked `{twitch_channel.display_name}` (`{twitch_channel.login}`) as {state_label}. "
                "Stored live-state rules and event-based auto-replies will use this persisted value."
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    def _ensure_permission(
        self,
        event: DiscordChannelLiveStateRequestedEvent,
    ) -> ThreadRecord | DiscordCommandResult:
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
                message="You do not have permission to update tracked channel live states.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread


@dataclass(slots=True)
class ChannelLiveStatePersistenceService:
    """Persist live/offline channel state changes received from any adapter."""

    event_bus: EventBus
    channel_repository: ChannelRepository

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.TWITCH_CHANNEL_LIVE_STATE_CHANGED, self.handle_change)

    def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None:
        updated_rows = self.channel_repository.set_live_state_for_twitch_channel(
            twitch_channel_id=event.twitch_channel_id,
            is_live=event.is_live,
            changed_at=event.changed_at.isoformat(),
        )
        logger.debug(
            "Persisted live-state change twitch_channel_id=%s is_live=%s rows=%s",
            event.twitch_channel_id,
            event.is_live,
            updated_rows,
        )
