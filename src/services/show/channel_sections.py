"""Focused `/show` renderers for tracked channels and channel events."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    ChannelRepository,
    ThreadRecord,
)
from src.localization import Localizer
from src.services.channel_event_display_index import ChannelEventDisplayIndexResolver
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    DISCORD_NOTIFY_ACTION,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
)

from .support import ShowFormattingService, ShowTwitchSubjectResolver


@dataclass(slots=True)
class ShowChannelsRenderer:
    channel_repository: ChannelRepository
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        channels = await self.channel_repository.list_channels_for_thread(thread.thread_id)
        if not channels:
            return self.formatter.render_section(
                "show.channel.section",
                self.localizer.text("show.channel.empty", language=language),
                language=language,
            )

        await self.resolver.preload_channel_ids(tuple(channel.twitch_channel_id for channel in channels))
        rows: list[str] = []
        for channel in channels:
            twitch_user = await self.resolver.resolve_channel_by_id(channel.twitch_channel_id)
            details: list[str] = []
            if channel.color:
                details.append(
                    self.localizer.text(
                        "show.channel.custom_color",
                        language=language,
                        COLOR=channel.color,
                    )
                )
            rows.append(
                self.localizer.text(
                    "show.channel.row",
                    language=language,
                    DISPLAY_NAME=twitch_user.display_name,
                    LOGIN=twitch_user.login,
                    DETAILS=(
                        ""
                        if not details
                        else self.localizer.text("show.channel.details", language=language, ITEMS=tuple(details))
                    ),
                )
            )
        return self.formatter.render_section(
            "show.channel.section",
            self.localizer.text("show.channel.rows", language=language, ITEMS=tuple(rows)),
            language=language,
        )


@dataclass(slots=True)
class ShowChannelEventsRenderer:
    channel_repository: ChannelRepository
    adapter_event_action_repository: AdapterEventActionRepository | None
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        if self.adapter_event_action_repository is None:
            return self.formatter.render_section(
                "show.channel_event.section",
                self.localizer.text("show.channel_event.empty", language=language),
                language=language,
            )

        channel_by_id = {
            channel.twitch_channel_id: channel
            for channel in await self.channel_repository.list_channels_for_thread(thread.thread_id)
        }
        rows: list[str] = []
        display_index_map = await ChannelEventDisplayIndexResolver(self.adapter_event_action_repository).build_index_map(
            thread.thread_id
        )
        actions = await self._channel_notification_actions(thread.thread_id)
        await self.resolver.preload_channel_ids(tuple(event.subject_id for event, _action in actions))
        for event, action in actions:
            display_index = display_index_map.get(event.event_id)
            if display_index is None:
                continue
            channel_user = await self.resolver.resolve_channel_by_id(event.subject_id)
            details = [
                self.localizer.text(
                    "show.channel_event.channel",
                    language=language,
                    DISPLAY_NAME=channel_user.display_name,
                    LOGIN=channel_user.login,
                ),
                self.localizer.text(
                    "show.channel_event.trigger",
                    language=language,
                    STATE=self.formatter.stream_state_label(
                        STREAM_EVENT_KEY_TO_STATE.get(event.event_key, event.event_key),
                        language=language,
                    ),
                ),
            ]
            tracked_channel = channel_by_id.get(event.subject_id)
            if tracked_channel is not None and tracked_channel.is_live is not None:
                details.append(
                    self.localizer.text(
                        "show.channel_event.live_state",
                        language=language,
                        STATE=self.formatter.stream_state_label(
                            "online" if tracked_channel.is_live else "offline",
                            language=language,
                        ),
                    )
                )
            if action.color:
                details.append(
                    self.localizer.text(
                        "show.channel_event.custom_color",
                        language=language,
                        COLOR=action.color,
                    )
                )
            if action.disabled:
                details.append(self.localizer.text("show.channel_event.disabled", language=language))
            rows.append(
                self.formatter.render_row(
                    row_key="show.channel_event.row",
                    details_key="show.channel_event.details",
                    head=self.localizer.text("show.channel_event.line", language=language, ID=display_index),
                    details=details,
                    language=language,
                )
            )
        if not rows:
            return self.formatter.render_section(
                "show.channel_event.section",
                self.localizer.text("show.channel_event.empty", language=language),
                language=language,
            )
        return self.formatter.render_section(
            "show.channel_event.section",
            self.localizer.text("show.channel_event.rows", language=language, ITEMS=tuple(rows)),
            language=language,
        )

    async def _channel_notification_actions(self, thread_id: int) -> list[tuple[AdapterEventRecord, AdapterEventActionRecord]]:
        if self.adapter_event_action_repository is None:
            return []
        rows = [
            (event, action)
            for event, action in await self.adapter_event_action_repository.list_actions_for_thread(
                thread_id,
                include_disabled=True,
            )
            if action.action_type == DISCORD_NOTIFY_ACTION
            and event.adapter_key == TWITCH_ADAPTER_KEY
            and event.subject_type == CHANNEL_SUBJECT_TYPE
            and event.event_key in STREAM_EVENT_KEY_TO_STATE
        ]
        rows.sort(key=lambda item: item[0].event_id)
        return rows
