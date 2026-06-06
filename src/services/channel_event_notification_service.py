"""Tracked Twitch channel live-state persistence and notification fan-out."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.database.connection import AdapterEventActionRepository, AdapterEventRepository, ChannelRepository, ThreadRepository
from src.discord_results import build_thread_result
from src.events.event_types import DiscordCommandResult, DiscordResultStyle, TwitchChannelLiveStateChangedEvent
from src.localization import Localizer
from src.services.twitch_runtime import safe_get_twitch_user_by_id
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    DISCORD_NOTIFY_ACTION,
    STREAM_OFFLINE_EVENT_KEY,
    STREAM_ONLINE_EVENT_KEY,
    TWITCH_ADAPTER_KEY,
)

logger = logging.getLogger(__name__)


class ChannelEventNotificationSender:
    """Interface used to emit Discord-side channel event notifications."""

    async def send_channel_result(
        self,
        discord_channel_id: int,
        result: DiscordCommandResult,
    ) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass(slots=True)
class ChannelLiveStatePersistenceService:
    """Persist live/offline channel state changes received from entrypoints."""

    channel_repository: ChannelRepository

    async def handle_change(self, event: TwitchChannelLiveStateChangedEvent) -> None:
        updated_rows = await self.channel_repository.set_live_state_for_twitch_channel(
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

    thread_repository: ThreadRepository
    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    channel_repository: ChannelRepository
    twitch_api: object
    notifier: ChannelEventNotificationSender
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    async def handle_change(
        self,
        event: TwitchChannelLiveStateChangedEvent,
        *,
        suppressed_events: set[tuple[int, int]] | None = None,
    ) -> None:
        event_key = STREAM_ONLINE_EVENT_KEY if event.is_live else STREAM_OFFLINE_EVENT_KEY
        configured_events = await self.adapter_event_repository.list_matching_events(
                adapter_key=TWITCH_ADAPTER_KEY,
                subject_type=CHANNEL_SUBJECT_TYPE,
                subject_id=event.twitch_channel_id,
                event_key=event_key,
                include_disabled=False,
            )
        
        if not configured_events:
            return

        channel_user = await safe_get_twitch_user_by_id(self.twitch_api, event.twitch_channel_id)
        channel_display_name = (
            (None if channel_user is None else channel_user.display_name) or event.twitch_channel_login or event.twitch_channel_id
        )
        channel_login = (None if channel_user is None else channel_user.login) or event.twitch_channel_login or event.twitch_channel_id
        for configured_event in configured_events:
            if suppressed_events and (configured_event.thread_id, configured_event.event_id) in suppressed_events:
                continue
            thread = await self.thread_repository.get_by_thread_id(configured_event.thread_id)
            if thread is None or not thread.enabled:
                continue
            notify_action = await self.adapter_event_action_repository.get_action(
                    event_id=configured_event.event_id,
                    action_type=DISCORD_NOTIFY_ACTION,
                )
            
            if notify_action is None or notify_action.disabled:
                continue
            await self.notifier.send_channel_result(
                thread.discord_channel_id,
                build_thread_result(
                    self.localizer,
                    "results.channel_event.went_live" if event.is_live else "results.channel_event.went_offline",
                    thread=thread,
                    color=notify_action.color,
                    style=DiscordResultStyle.INFO,
                    ephemeral=False,
                    sources={
                        "view": {
                            "channel": {
                                "display_name": channel_display_name,
                                "login": channel_login,
                            }
                        }
                    },
                ),
            )
