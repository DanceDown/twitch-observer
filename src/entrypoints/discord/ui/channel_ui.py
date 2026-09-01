"""Discord UI for `/channel`."""

from __future__ import annotations

import discord

from ..dispatch import dispatch_add_tracked_channel, dispatch_remove_tracked_channel, dispatch_set_tracked_channel_color
from ..helpers import complete_bound_result, defer_interaction_response, normalize_optional_text
from ..ui_data import TrackedChannelPresentation
from .selects import window_with_included_items
from .shared import DiscordModalContext


class ChannelNameModal(discord.ui.Modal):
    """Simple modal used for adding tracked Twitch channels."""

    def __init__(
        self,
        *,
        context: DiscordModalContext,
    ) -> None:
        """Create the modal for entering a Twitch channel login."""
        super().__init__(
            title=context.localizer.text("discord.channel_ui.modal.add.title", language=context.language),
            timeout=300,
        )
        self._context = context
        self.channel_name = discord.ui.TextInput(
            label=context.localizer.text("discord.channel_ui.modal.add.name_label", language=context.language),
            placeholder=context.localizer.text("discord.channel_ui.modal.add.name_placeholder", language=context.language),
            required=True,
        )
        self.add_item(self.channel_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the entered Twitch channel name."""
        await defer_interaction_response(interaction, ephemeral=True)
        result = await dispatch_add_tracked_channel(
            self._context.services,
            discord_channel_id=self._context.discord_channel_id,
            requester_id=self._context.requester_id,
            twitch_channel_login=self.channel_name.value.strip(),
        )
        await complete_bound_result(interaction, bound_message=self._context.bound_message, result=result)


class ChannelSelectionModal(discord.ui.Modal):
    """Select one tracked channel for removal or color management."""

    def __init__(
        self,
        *,
        context: DiscordModalContext,
        action: str,
        tracked_channels: list[TrackedChannelPresentation],
        default_login: str | None = None,
        default_color: str | None = None,
    ) -> None:
        """Create the modal for selecting a channel and optional color."""
        super().__init__(
            title=context.localizer.text(f"discord.channel_ui.modal.{action}.title", language=context.language),
            timeout=300,
        )
        self._context = context
        self._action = action
        visible_channels = window_with_included_items(
            tracked_channels,
            key=lambda channel: channel.login,
            included_keys=[default_login] if default_login else [],
        )
        self.channel = discord.ui.Label(
            text=context.localizer.text("discord.channel_ui.modal.select.channel_label", language=context.language),
            description=context.localizer.text("discord.channel_ui.modal.select.channel_description", language=context.language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.login,
                        description=channel.login[:100],
                        default=channel.login == default_login,
                    )
                    for channel in visible_channels
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.channel)
        if action == "color":
            self.color = discord.ui.TextInput(
                label=context.localizer.text("discord.channel_ui.modal.select.color_label", language=context.language),
                placeholder=context.localizer.text("discord.channel_ui.modal.select.color_placeholder", language=context.language),
                default=default_color,
                required=False,
            )
            self.add_item(self.color)
        else:
            self.color = None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the selected tracked-channel action."""
        await defer_interaction_response(interaction, ephemeral=True)
        login = self.channel.component.values[0]
        if self._action == "color":
            result = await dispatch_set_tracked_channel_color(
                self._context.services,
                discord_channel_id=self._context.discord_channel_id,
                requester_id=self._context.requester_id,
                twitch_channel_login=login,
                color=normalize_optional_text(self.color.value if self.color is not None else None),
            )
        else:
            result = await dispatch_remove_tracked_channel(
                self._context.services,
                discord_channel_id=self._context.discord_channel_id,
                requester_id=self._context.requester_id,
                twitch_channel_login=login,
            )
        await complete_bound_result(interaction, bound_message=self._context.bound_message, result=result)
