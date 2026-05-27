"""Discord UI for configuring Twitch live/offline notifications."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import StreamEventKind
from src.localization import Localizer

from ..dispatch import (
    dispatch_add_channel_event,
    dispatch_disable_channel_event,
    dispatch_enable_channel_event,
    dispatch_remove_channel_event,
)
from ..helpers import complete_bound_result
from ..ui_data import AdapterEventActionPresentation, TrackedChannelPresentation


class ChannelEventModal(discord.ui.Modal):
    """Choose one tracked channel and configure one external channel event."""

    def __init__(
        self,
        *,
        title: str,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        tracked_channels: list[TrackedChannelPresentation],
        event_key: str,
        localizer: Localizer,
        language: str,
        default_channel_id: str | None = None,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._event_key = event_key
        self._bound_message = bound_message
        state_text = localizer.text(f"discord.live_state_ui.states.{event_key}", language=language)
        self.channel = discord.ui.Label(
            text=localizer.text("discord.live_state_ui.modal.channel_label", language=language),
            description=localizer.text(
                "discord.live_state_ui.modal.channel_description",
                language=language,
                STATE=state_text,
            ),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.user_id,
                        description=channel.login[:100],
                        default=channel.user_id == default_channel_id or channel.login == default_channel_id,
                    )
                    for channel in tracked_channels[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        result = await dispatch_add_channel_event(
            self._services,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            twitch_channel_id=self.channel.component.values[0],
            event_kind=StreamEventKind(self._event_key),
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ChannelEventActionModal(discord.ui.Modal):
    """Remove, disable, or enable one configured live/offline notification."""

    def __init__(
        self,
        *,
        title: str,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        actions: list[AdapterEventActionPresentation],
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.notification = discord.ui.Label(
            text=localizer.text("discord.live_state_ui.action.notification_label", language=language),
            description=localizer.text("discord.live_state_ui.action.notification_description", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_notification_label(item, localizer=localizer, language=language),
                        value=f"{item.event.event.subject_id}:{item.event.event.event_key}",
                        description=item.event.channel.login[:100],
                    )
                    for item in actions[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.notification)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        twitch_channel_id, event_key = self.notification.component.values[0].split(":", 1)
        event_kind = StreamEventKind(event_key)
        if self._action == "remove":
            result = await dispatch_remove_channel_event(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                twitch_channel_id=twitch_channel_id,
                event_kind=event_kind,
            )
        elif self._action == "disable":
            result = await dispatch_disable_channel_event(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                twitch_channel_id=twitch_channel_id,
                event_kind=event_kind,
            )
        else:
            result = await dispatch_enable_channel_event(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                twitch_channel_id=twitch_channel_id,
                event_kind=event_kind,
            )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


def _notification_label(
    item: AdapterEventActionPresentation,
    *,
    localizer: Localizer,
    language: str,
) -> str:
    state = localizer.text(f"discord.live_state_ui.states.{item.event.event.event_key}", language=language)
    return localizer.text(
        "discord.live_state_ui.action.notification_option",
        language=language,
        CHANNEL=item.event.channel.display_name,
        STATE=state,
    )[:100]
