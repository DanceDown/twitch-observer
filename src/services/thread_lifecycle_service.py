"""Business logic for explicitly joining and leaving Discord contexts."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError
from src.database.connection import ChannelRepository, ThreadRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    DiscordThreadRequestedEvent,
    EventType,
    TwitchTrackedChannelsChangedEvent,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.services.channel_command_service import IRCChannelManager
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
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_THREAD_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordThreadRequestedEvent) -> None:
        """Apply the requested lifecycle action and complete the result future."""
        try:
            result = await self._handle_action(event)
        except TwitchAPIError as error:
            logger.warning("Best-effort Twitch metadata lookup failed during thread lifecycle: %s", error)
            result = self.localizer.result(
                "results.twitch_api_error",
                language=self.localizer.default_language,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
            )
        except Exception as error:
            logger.exception("Unexpected error while handling thread lifecycle command.")
            result = self.localizer.result(
                "results.unexpected_error",
                language=self.localizer.default_language,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
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
        if event.action == "language":
            return self._set_context_language(event)
        return self.localizer.result(
            "results.thread.unsupported_action",
            language=self.localizer.default_language,
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    async def _join_context(self, event: DiscordThreadRequestedEvent) -> DiscordCommandResult:
        existing = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if existing is not None:
            if existing.owner_id == event.requester_id:
                return self.localizer.thread_result(
                    "results.thread.already_joined",
                    thread=existing,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            return self.localizer.thread_result(
                "results.thread.already_joined_other_owner",
                thread=existing,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        created = self.thread_repository.create(owner_id=event.requester_id, discord_channel_id=event.discord_channel_id)
        logger.debug(
            "Joined Discord context discord_channel_id=%s owner_id=%s",
            event.discord_channel_id,
            event.requester_id,
        )
        return self.localizer.thread_result(
            "results.thread.joined",
            thread=created,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _leave_context(self, event: DiscordThreadRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.LEAVE_CONTEXT,
        ):
            return self.localizer.thread_result(
                "results.thread.leave_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        removed_channel_ids = sorted(
            {channel.twitch_channel_id for channel in self.channel_repository.list_channels_for_thread(thread.thread_id)}
        )
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
            return self.localizer.result(
                "results.not_joined",
                language=self.localizer.default_language,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        logger.debug(
            "Left Discord context discord_channel_id=%s owner_id=%s removed_twitch_channels=%s",
            event.discord_channel_id,
            event.requester_id,
            removed_channel_ids,
        )
        await self.event_bus.publish(
            EventType.TWITCH_TRACKED_CHANNELS_CHANGED,
            TwitchTrackedChannelsChangedEvent(reason="thread_left"),
        )
        return self.localizer.thread_result(
            "results.thread.left",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    def _set_context_enabled(self, event: DiscordThreadRequestedEvent, *, enabled: bool) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.CONTROL_OBSERVER,
        ):
            return self.localizer.thread_result(
                "results.thread.enable_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if thread.enabled == enabled:
            return self.localizer.thread_result(
                "results.thread.already_on" if enabled else "results.thread.already_off",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.thread_repository.set_enabled(discord_channel_id=event.discord_channel_id, enabled=enabled)
        assert updated is not None
        return self.localizer.thread_result(
            "results.thread.enabled" if enabled else "results.thread.disabled",
            thread=updated,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    def _set_context_color(self, event: DiscordThreadRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.CONTROL_OBSERVER,
        ):
            return self.localizer.thread_result(
                "results.thread.color_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if event.clear_color:
            updated = self.thread_repository.set_color(discord_channel_id=event.discord_channel_id, color=None)
            assert updated is not None
            return self.localizer.thread_result(
                "results.thread.color_cleared",
                thread=updated,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )
        if event.color is None or not re.fullmatch(r"#[0-9A-Fa-f]{6}", event.color.strip()):
            return self.localizer.thread_result(
                "results.validation_error",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL="Color must use the format `#RRGGBB` or set `clear:true`.",
            )
        updated = self.thread_repository.set_color(
            discord_channel_id=event.discord_channel_id,
            color=event.color.strip(),
        )
        assert updated is not None
        return self.localizer.thread_result(
            "results.thread.color_updated",
            thread=updated,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            COLOR=updated.color or "",
        )

    def _set_context_language(self, event: DiscordThreadRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.CONTROL_OBSERVER,
        ):
            return self.localizer.thread_result(
                "results.thread.language_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        requested_language = self.localizer.normalize_language(event.language)
        if not self.localizer.has_language(requested_language):
            return self.localizer.thread_result(
                "results.validation_error",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=(
                    "Unsupported language. Available languages: "
                    + ", ".join(f"`{language}`" for language in self.localizer.available_languages())
                ),
            )
        updated = self.thread_repository.set_language(
            discord_channel_id=event.discord_channel_id,
            language=requested_language,
        )
        assert updated is not None
        language_name = self.localizer.text(
            "common.language_name",
            language=requested_language,
        )
        return self.localizer.thread_result(
            "results.thread.language_updated",
            thread=updated,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            LANGUAGE_NAME=language_name,
            LANGUAGE_CODE=requested_language,
        )

