"""Discord UI for `/channel`."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.localization import Localizer

from ..dispatch import dispatch_add_tracked_channel, dispatch_remove_tracked_channel, dispatch_set_tracked_channel_color
from ..helpers import complete_bound_result, normalize_optional_text
from ..ui_data import TrackedChannelPresentation


class ChannelNameModal(discord.ui.Modal):
    """Simple modal used for adding tracked Twitch channels."""

    def __init__(
        self,
        *,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.channel_ui.modal.add.title", language=language), timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        self.channel_name = discord.ui.TextInput(
            label=localizer.text("discord.channel_ui.modal.add.name_label", language=language),
            placeholder=localizer.text("discord.channel_ui.modal.add.name_placeholder", language=language),
            required=True,
        )
        self.add_item(self.channel_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the entered Twitch channel name."""
        result = await dispatch_add_tracked_channel(
            self._services,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            twitch_channel_login=self.channel_name.value.strip(),
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ChannelSelectionModal(discord.ui.Modal):
    """Select one tracked channel for removal or color management."""

    def __init__(
        self,
        *,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        tracked_channels: list[TrackedChannelPresentation],
        localizer: Localizer,
        language: str,
        default_login: str | None = None,
        default_color: str | None = None,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(
            title=localizer.text(f"discord.channel_ui.modal.{action}.title", language=language),
            timeout=300,
        )
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.channel = discord.ui.Label(
            text=localizer.text("discord.channel_ui.modal.select.channel_label", language=language),
            description=localizer.text("discord.channel_ui.modal.select.channel_description", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.login,
                        description=channel.login[:100],
                        default=channel.login == default_login,
                    )
                    for channel in tracked_channels[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.channel)
        if action == "color":
            self.color = discord.ui.TextInput(
                label=localizer.text("discord.channel_ui.modal.select.color_label", language=language),
                placeholder=localizer.text("discord.channel_ui.modal.select.color_placeholder", language=language),
                default=default_color,
                required=False,
            )
            self.add_item(self.color)
        else:
            self.color = None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the selected tracked-channel action."""
        login = self.channel.component.values[0]
        if self._action == "color":
            result = await dispatch_set_tracked_channel_color(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                twitch_channel_login=login,
                color=normalize_optional_text(self.color.value if self.color is not None else None),
            )
        else:
            result = await dispatch_remove_tracked_channel(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                twitch_channel_login=login,
            )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)
