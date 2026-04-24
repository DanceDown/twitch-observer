from __future__ import annotations

"""Tracked Twitch channel events, persistence and Discord notifications."""

from dataclasses import dataclass
import logging

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
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_CHANNEL_EVENT_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordChannelEventRequestedEvent) -> None:
        try:
            result = await self._handle_action(event)
        except ValueError as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling channel event command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
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
            return DiscordCommandResult(
                title="Channel Not Tracked",
                message="This Twitch channel is not tracked in the current Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if event.event_key not in {STREAM_ONLINE_EVENT_KEY, STREAM_OFFLINE_EVENT_KEY}:
            raise ValueError("Unsupported tracked channel event.")

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
        action_label = "live" if event.event_key == STREAM_ONLINE_EVENT_KEY else "offline"
        if existing_action is None:
            title = "Notification Added"
            message = f"This Discord channel will now be notified when the tracked Twitch channel goes {action_label}."
        elif existing_action.disabled:
            title = "Notification Enabled"
            message = f"The {action_label} notification was re-enabled for this tracked Twitch channel."
        else:
            title = "Already Configured"
            message = f"A {action_label} notification is already configured for this tracked Twitch channel."
        logger.debug(
            "Configured tracked channel event thread_id=%s event_id=%s action=%s event_key=%s",
            thread.thread_id,
            adapter_event.event_id,
            action.action_type,
            adapter_event.event_key,
        )
        return DiscordCommandResult(
            title=title,
            message=message,
            style=DiscordResultStyle.SUCCESS if title != "Already Configured" else DiscordResultStyle.INFO,
            ephemeral=title == "Already Configured",
        )

    def _ensure_permission(
        self,
        event: DiscordChannelEventRequestedEvent,
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
                message="You do not have permission to configure tracked channel notifications.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread


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
        state_text = "live" if event.is_live else "offline"
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
                DiscordCommandResult(
                    title=f"Channel Went {'Live' if event.is_live else 'Offline'}",
                    message=f"`{channel_name}` is now {state_text}.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=False,
                ),
            )
