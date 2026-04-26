from __future__ import annotations

"""Tracked Twitch channel events, persistence and Discord notifications."""

import logging
from dataclasses import dataclass, field

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError
from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRepository,
    ThreadRecord,
    ThreadRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordChannelEventRequestedEvent,
    DiscordCommandResult,
    DiscordResultStyle,
    EventType,
    TwitchChannelLiveStateChangedEvent,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    DISCORD_NOTIFY_ACTION,
    STREAM_OFFLINE_EVENT_KEY,
    STREAM_ONLINE_EVENT_KEY,
    TWITCH_ADAPTER_KEY,
)
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


class ChannelEventNotificationSender:
    """Interface used to emit Discord-side channel event notifications."""

    async def send_channel_result(
        self,
        discord_channel_id: int,
        result: DiscordCommandResult,
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(slots=True)
class ChannelEventCommandService:
    """Handle `/live` and `/offline` as notification-trigger configuration."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    twitch_api: TwitchAPIClient | None = None
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_CHANNEL_EVENT_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordChannelEventRequestedEvent) -> None:
        try:
            result = await self._handle_action(event)
        except ValueError as error:
            result = self._event_result(
                event,
                "results.validation_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling channel event command.")
            result = self._event_result(
                event,
                "results.unexpected_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_action(self, event: DiscordChannelEventRequestedEvent) -> DiscordCommandResult:
        thread = self._ensure_permission(event)
        if isinstance(thread, DiscordCommandResult):
            return thread

        tracked_channel = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, event.twitch_channel_id)
        if tracked_channel is None:
            return self.localizer.thread_result(
                "results.channel_event.channel_not_tracked",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if event.event_key not in {STREAM_ONLINE_EVENT_KEY, STREAM_OFFLINE_EVENT_KEY}:
            raise ValueError(self.localizer.text("results.channel_event.unsupported_event", language=thread.language))

        channel_name = await self._channel_display_name(event.twitch_channel_id)
        if event.action == "add":
            return self._add_notification(event, thread, channel_name)
        if event.action in {"remove", "disable", "enable"}:
            return self._update_notification(event, thread, channel_name)
        raise ValueError(self.localizer.text("results.channel_event.unsupported_action", language=thread.language))

    def _add_notification(
        self,
        event: DiscordChannelEventRequestedEvent,
        thread: ThreadRecord,
        channel_name: str,
    ) -> DiscordCommandResult:
        adapter_event = self.adapter_event_repository.upsert_event(
            thread_id=thread.thread_id,
            adapter_key=TWITCH_ADAPTER_KEY,
            subject_type=CHANNEL_SUBJECT_TYPE,
            subject_id=event.twitch_channel_id,
            event_key=event.event_key,
        )
        existing_action = self.adapter_event_action_repository.get_action(
            event_id=adapter_event.event_id,
            action_type=DISCORD_NOTIFY_ACTION,
        )
        action = self.adapter_event_action_repository.upsert_action(
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
        return self.localizer.thread_result(
            key,
            thread=thread,
            STATE=self._state_label(event.event_key, thread),
            CHANNEL=channel_name,
            style=style,
            ephemeral=ephemeral,
        )

    def _update_notification(
        self,
        event: DiscordChannelEventRequestedEvent,
        thread: ThreadRecord,
        channel_name: str,
    ) -> DiscordCommandResult:
        adapter_event = self.adapter_event_repository.get_event(
            thread_id=thread.thread_id,
            adapter_key=TWITCH_ADAPTER_KEY,
            subject_type=CHANNEL_SUBJECT_TYPE,
            subject_id=event.twitch_channel_id,
            event_key=event.event_key,
        )
        existing_action = (
            None
            if adapter_event is None
            else self.adapter_event_action_repository.get_action(
                event_id=adapter_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
            )
        )
        if adapter_event is None or existing_action is None:
            return self.localizer.thread_result(
                "results.channel_event.none_configured",
                thread=thread,
                STATE=self._state_label(event.event_key, thread),
                CHANNEL=channel_name,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if event.action == "remove":
            self.adapter_event_action_repository.remove_action(
                event_id=adapter_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
            )
            key = "results.channel_event.notification_removed"
        elif event.action == "disable":
            if existing_action.disabled:
                return self.localizer.thread_result(
                    "results.channel_event.already_disabled",
                    thread=thread,
                    STATE=self._state_label(event.event_key, thread),
                    CHANNEL=channel_name,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            self.adapter_event_action_repository.set_action_disabled(
                event_id=adapter_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
                disabled=True,
            )
            key = "results.channel_event.notification_disabled"
        else:
            if not existing_action.disabled:
                return self.localizer.thread_result(
                    "results.channel_event.already_enabled",
                    thread=thread,
                    STATE=self._state_label(event.event_key, thread),
                    CHANNEL=channel_name,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            self.adapter_event_action_repository.set_action_disabled(
                event_id=adapter_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
                disabled=False,
            )
            key = "results.channel_event.notification_enabled"

        return self.localizer.thread_result(
            key,
            thread=thread,
            STATE=self._state_label(event.event_key, thread),
            CHANNEL=channel_name,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _channel_display_name(self, twitch_channel_id: str) -> str:
        if self.twitch_api is None:
            return twitch_channel_id
        try:
            return (await self.twitch_api.get_user_by_id(twitch_channel_id)).display_name
        except TwitchAPIError:
            return twitch_channel_id

    def _state_label(self, event_key: str, thread: ThreadRecord) -> str:
        state_key = "live" if event_key == STREAM_ONLINE_EVENT_KEY else "offline"
        return self.localizer.text(f"results.channel_event.state.{state_key}", language=thread.language)

    def _ensure_permission(
        self,
        event: DiscordChannelEventRequestedEvent,
    ) -> ThreadRecord | DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if thread is None:
            return self.localizer.result(
                "results.not_joined",
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
                "results.channel_event.permission_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    def _event_result(
        self,
        event: DiscordChannelEventRequestedEvent,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        return self.localizer.thread_result(key, thread=thread, style=style, ephemeral=ephemeral, **placeholders)


@dataclass(slots=True)
class ChannelLiveStatePersistenceService:
    """Persist live/offline channel state changes received from adapters."""

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


@dataclass(slots=True)
class ChannelEventNotificationService:
    """Emit Discord notifications for configured tracked channel events."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    notifier: ChannelEventNotificationSender | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.TWITCH_CHANNEL_LIVE_STATE_CHANGED, self.handle_change)

    async def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None:
        if self.notifier is None:
            return
        event_key = STREAM_ONLINE_EVENT_KEY if event.is_live else STREAM_OFFLINE_EVENT_KEY
        configured_events = self.adapter_event_repository.list_matching_events(
            adapter_key=TWITCH_ADAPTER_KEY,
            subject_type=CHANNEL_SUBJECT_TYPE,
            subject_id=event.twitch_channel_id,
            event_key=event_key,
            include_disabled=False,
        )
        if not configured_events:
            return

        channel_name = event.twitch_channel_login or event.twitch_channel_id
        for configured_event in configured_events:
            thread = self.thread_repository.get_by_thread_id(configured_event.thread_id)
            if thread is None or not thread.enabled:
                continue
            notify_action = self.adapter_event_action_repository.get_action(
                event_id=configured_event.event_id,
                action_type=DISCORD_NOTIFY_ACTION,
            )
            if notify_action is None or notify_action.disabled:
                continue
            await self.notifier.send_channel_result(
                thread.discord_channel_id,
                self.localizer.thread_result(
                    "results.channel_event.went_live" if event.is_live else "results.channel_event.went_offline",
                    thread=thread,
                    CHANNEL=channel_name,
                    style=DiscordResultStyle.INFO,
                    ephemeral=False,
                ),
            )
