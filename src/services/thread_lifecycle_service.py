from __future__ import annotations

"""Business logic for explicitly joining and leaving Discord contexts."""

from dataclasses import dataclass
import logging
import re

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError
from src.database.connection import ChannelRepository, ThreadRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    DiscordThreadRequestedEvent,
    EventType,
)
from src.services.channel_command_service import IRCChannelManager
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ThreadLifecycleService:
    """Handle `/join` and `/leave` for one Discord channel or DM context."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    twitch_api: TwitchAPIClient
    irc_manager: IRCChannelManager
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_THREAD_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordThreadRequestedEvent) -> None:
        """Apply the requested lifecycle action and complete the result future."""
        try:
            result = await self._handle_action(event)
        except TwitchAPIError as error:
            logger.warning("Best-effort Twitch metadata lookup failed during thread lifecycle: %s", error)
            result = DiscordCommandResult(
                title="Twitch API Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling thread lifecycle command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_action(self, event: DiscordThreadRequestedEvent) -> DiscordCommandResult:
        if event.action == "join":
            return await self._join_context(event)
        if event.action == "leave":
            return await self._leave_context(event)
        if event.action == "enable":
            return self._set_context_enabled(event, enabled=True)
        if event.action == "disable":
            return self._set_context_enabled(event, enabled=False)
        if event.action == "color":
            return self._set_context_color(event)
        return DiscordCommandResult(
            title="Validation Error",
            message="Unsupported action. Use `join`, `leave`, `enable`, `disable`, or `color`.",
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    async def _join_context(self, event: DiscordThreadRequestedEvent) -> DiscordCommandResult:
        existing = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if existing is not None:
            if existing.owner_id == event.requester_id:
                return DiscordCommandResult(
                    title="Already Joined",
                    message="This Discord channel is already connected to the observer.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            return DiscordCommandResult(
                title="Permission Denied",
                message="This Discord channel is already connected by another owner.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        self.thread_repository.create(owner_id=event.requester_id, discord_channel_id=event.discord_channel_id)
        logger.debug(
            "Joined Discord context discord_channel_id=%s owner_id=%s",
            event.discord_channel_id,
            event.requester_id,
        )
        return DiscordCommandResult(
            title="Observer Joined",
            message="The bot joined this Discord channel and is ready for configuration.",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _leave_context(self, event: DiscordThreadRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.LEAVE_CONTEXT,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message="You do not have permission to make the bot leave this Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        removed_channel_ids = sorted({channel.twitch_channel_id for channel in self.channel_repository.list_channels_for_thread(thread.thread_id)})
        for twitch_channel_id in removed_channel_ids:
            self.channel_repository.remove_channel(thread.thread_id, twitch_channel_id)
            if self.channel_repository.count_threads_by_twitch_channel_id(twitch_channel_id) == 0:
                try:
                    twitch_user = await self.twitch_api.get_user_by_id(twitch_channel_id)
                except TwitchAPIError:
                    logger.warning(
                        "Could not resolve Twitch channel id=%s while leaving discord_channel_id=%s; skipping IRC PART.",
                        twitch_channel_id,
                        event.discord_channel_id,
                    )
                else:
                    await self.irc_manager.leave_channel(twitch_user.login)

        deleted = self.thread_repository.delete_by_discord_channel_id(event.discord_channel_id)
        if deleted is None:
            return DiscordCommandResult(
                title="Not Joined",
                message="This Discord channel is not connected yet. Use `/join` first.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        logger.debug(
            "Left Discord context discord_channel_id=%s owner_id=%s removed_twitch_channels=%s",
            event.discord_channel_id,
            event.requester_id,
            removed_channel_ids,
        )
        return DiscordCommandResult(
            title="Observer Left",
            message="The bot left this Discord channel and deleted all saved configuration for it.",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    def _set_context_enabled(self, event: DiscordThreadRequestedEvent, *, enabled: bool) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.CONTROL_OBSERVER,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message="You do not have permission to change the observer state in this Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if thread.enabled == enabled:
            return DiscordCommandResult(
                title="Already On" if enabled else "Already Off",
                message="The observer is already enabled in this Discord channel."
                if enabled
                else "The observer is already disabled in this Discord channel.",
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.thread_repository.set_enabled(discord_channel_id=event.discord_channel_id, enabled=enabled)
        assert updated is not None
        return DiscordCommandResult(
            title="Observer Enabled" if enabled else "Observer Disabled",
            message="The observer is now enabled in this Discord channel."
            if enabled
            else "The observer is now disabled in this Discord channel.",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    def _set_context_color(self, event: DiscordThreadRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.CONTROL_OBSERVER,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message="You do not have permission to change the observer color in this Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if event.clear_color:
            updated = self.thread_repository.set_color(discord_channel_id=event.discord_channel_id, color=None)
            assert updated is not None
            return DiscordCommandResult(
                title="Observer Color Cleared",
                message="Cleared the custom color for this Discord observer context.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )
        if event.color is None or not re.fullmatch(r"#[0-9A-Fa-f]{6}", event.color.strip()):
            return DiscordCommandResult(
                title="Validation Error",
                message="Color must use the format `#RRGGBB` or set `clear:true`.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        updated = self.thread_repository.set_color(
            discord_channel_id=event.discord_channel_id,
            color=event.color.strip(),
        )
        assert updated is not None
        return DiscordCommandResult(
            title="Observer Color Updated",
            message=f"Set the color for this Discord observer context to `{updated.color}`.",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )
