"""Discord UI for configuring Twitch live/offline notifications."""

from __future__ import annotations

import discord

from src.events.commands import SetChannelEventColorCommand
from src.events.twitch_events import StreamEventKind
from src.localization import Localizer

from ..dispatch import (
    dispatch_add_channel_event,
    dispatch_remove_channel_event,
    dispatch_set_channel_event_color,
)
from ..helpers import complete_bound_result, defer_interaction_response, normalize_optional_text
from ..ui_data import AdapterEventActionPresentation, TrackedChannelPresentation
from .selects import window_with_included_items
from .shared import DiscordModalContext


class UnsupportedLivePingActionError(ValueError):
    """Raised when a live/offline UI modal receives an unknown action key."""

    def __init__(self, action: str) -> None:
        """Create an error for an unsupported live-ping action key."""
        super().__init__(f"Unsupported live ping action `{action}`.")


class ChannelEventModal(discord.ui.Modal):
    """Choose one tracked channel and configure one external channel event."""

    def __init__(
        self,
        *,
        title: str,
        context: DiscordModalContext,
        tracked_channels: list[TrackedChannelPresentation],
        default_channel_id: str | None = None,
        default_event_key: str | None = None,
    ) -> None:
        """Create the modal used to add live/offline notifications."""
        super().__init__(title=title, timeout=300)
        self._context = context
        included_channel_logins = [
            channel.login for channel in tracked_channels if channel.user_id == default_channel_id or channel.login == default_channel_id
        ]
        visible_channels = window_with_included_items(
            tracked_channels,
            key=lambda channel: channel.login,
            included_keys=included_channel_logins,
        )
        self.state = discord.ui.Label(
            text=context.localizer.text("discord.live_state_ui.modal.state_label", language=context.language),
            description=context.localizer.text("discord.live_state_ui.modal.state_description", language=context.language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=context.localizer.text("discord.live_state_ui.modal.state_option.online", language=context.language),
                        value=StreamEventKind.ONLINE.value,
                        default=default_event_key == StreamEventKind.ONLINE.value,
                    ),
                    discord.SelectOption(
                        label=context.localizer.text("discord.live_state_ui.modal.state_option.offline", language=context.language),
                        value=StreamEventKind.OFFLINE.value,
                        default=default_event_key == StreamEventKind.OFFLINE.value,
                    ),
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.state)
        self.channel = discord.ui.Label(
            text=context.localizer.text("discord.live_state_ui.modal.channel_label", language=context.language),
            description=context.localizer.text("discord.live_state_ui.modal.channel_description", language=context.language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.user_id,
                        description=channel.login[:100],
                        default=channel.user_id == default_channel_id or channel.login == default_channel_id,
                    )
                    for channel in visible_channels
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the selected channel-event notification creation."""
        await defer_interaction_response(interaction, ephemeral=True)
        result = await dispatch_add_channel_event(
            self._context.services,
            discord_channel_id=self._context.discord_channel_id,
            requester_id=self._context.requester_id,
            twitch_channel_id=self.channel.component.values[0],
            event_kind=StreamEventKind(self.state.component.values[0]),
        )
        await complete_bound_result(interaction, bound_message=self._context.bound_message, result=result)


class ChannelEventActionModal(discord.ui.Modal):
    """Remove one configured live/offline notification."""

    def __init__(
        self,
        *,
        title: str,
        context: DiscordModalContext,
        action: str,
        actions: list[AdapterEventActionPresentation],
        default_notification_value: str | None = None,
    ) -> None:
        """Create the modal used to remove live/offline notifications."""
        super().__init__(title=title, timeout=300)
        self._context = context
        self._action = action
        visible_actions = window_with_included_items(
            actions,
            key=lambda item: f"{item.event.event.subject_id}:{item.event.event.event_key}",
            included_keys=[default_notification_value] if default_notification_value else [],
        )
        self.notification = discord.ui.Label(
            text=context.localizer.text("discord.live_state_ui.action.notification_label", language=context.language),
            description=context.localizer.text("discord.live_state_ui.action.notification_description", language=context.language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_notification_label(item, localizer=context.localizer, language=context.language),
                        value=f"{item.event.event.subject_id}:{item.event.event.event_key}",
                        description=item.event.channel.login[:100],
                        default=f"{item.event.event.subject_id}:{item.event.event.event_key}" == default_notification_value,
                    )
                    for item in visible_actions
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.notification)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch removal of the selected live/offline notification."""
        await defer_interaction_response(interaction, ephemeral=True)
        twitch_channel_id, event_key = self.notification.component.values[0].split(":", 1)
        if self._action != "remove":
            raise UnsupportedLivePingActionError(self._action)
        result = await dispatch_remove_channel_event(
            self._context.services,
            discord_channel_id=self._context.discord_channel_id,
            requester_id=self._context.requester_id,
            twitch_channel_id=twitch_channel_id,
            event_kind=StreamEventKind(event_key),
        )
        await complete_bound_result(interaction, bound_message=self._context.bound_message, result=result)


class ChannelEventColorModal(discord.ui.Modal):
    """Set or clear the color of one configured live/offline ping."""

    def __init__(
        self,
        *,
        title: str,
        context: DiscordModalContext,
        actions: list[AdapterEventActionPresentation],
        default_notification_value: str | None = None,
        default_color: str | None = None,
    ) -> None:
        """Create the modal used to set or clear notification colors."""
        super().__init__(title=title, timeout=300)
        self._context = context
        visible_actions = window_with_included_items(
            actions,
            key=lambda item: f"{item.event.event.subject_id}:{item.event.event.event_key}",
            included_keys=[default_notification_value] if default_notification_value else [],
        )
        self.notification = discord.ui.Label(
            text=context.localizer.text("discord.live_state_ui.action.notification_label", language=context.language),
            description=context.localizer.text("discord.live_state_ui.action.notification_description", language=context.language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_notification_label(item, localizer=context.localizer, language=context.language),
                        value=f"{item.event.event.subject_id}:{item.event.event.event_key}",
                        description=item.event.channel.login[:100],
                        default=f"{item.event.event.subject_id}:{item.event.event.event_key}" == default_notification_value,
                    )
                    for item in visible_actions
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.notification)
        self.color = discord.ui.TextInput(
            label=context.localizer.text("discord.live_state_ui.action.color_label", language=context.language),
            placeholder=context.localizer.text("discord.live_state_ui.action.color_placeholder", language=context.language),
            default=default_color,
            required=False,
            max_length=7,
        )
        self.add_item(self.color)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the selected live/offline notification color update."""
        await defer_interaction_response(interaction, ephemeral=True)
        twitch_channel_id, event_key = self.notification.component.values[0].split(":", 1)
        result = await dispatch_set_channel_event_color(
            self._context.services,
            SetChannelEventColorCommand(
                discord_channel_id=self._context.discord_channel_id,
                requester_id=self._context.requester_id,
                twitch_channel_id=twitch_channel_id,
                event_kind=StreamEventKind(event_key),
                color=normalize_optional_text(self.color.value),
            ),
        )
        await complete_bound_result(interaction, bound_message=self._context.bound_message, result=result)


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
        sources={
            "view": {
                "display_id": item.display_index or item.event.event.event_id,
                "channel": item.event.channel.display_name,
                "state": state,
            }
        },
    )[:100]
