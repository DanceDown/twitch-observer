from __future__ import annotations

"""Discord UI for `/channel`."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordResultStyle
from src.localization import Localizer

from ..dispatch import dispatch_channel_command
from ..helpers import complete_bound_result, normalize_optional_text
from ..ui_data import DiscordUIDataProvider, TrackedChannelPresentation
from .shared import BaseFormView, resolve_context_language


class ChannelNameModal(discord.ui.Modal):
    """Simple modal used for adding tracked Twitch channels."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.channel_ui.modal.add.title", language=language), timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.channel_name = discord.ui.TextInput(
            label=localizer.text("discord.channel_ui.modal.add.name_label", language=language),
            placeholder=localizer.text("discord.channel_ui.modal.add.name_placeholder", language=language),
            required=True,
        )
        self.add_item(self.channel_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the entered Twitch channel name."""
        result = await dispatch_channel_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action=self._action,
            twitch_channel_login=self.channel_name.value.strip(),
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ChannelSelectionModal(discord.ui.Modal):
    """Select one tracked channel for removal or color management."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        tracked_channels: list[TrackedChannelPresentation],
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(
            title=localizer.text(f"discord.channel_ui.modal.{action}.title", language=language),
            timeout=300,
        )
        self._event_bus = event_bus
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
                required=False,
            )
            self.add_item(self.color)
        else:
            self.color = None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the selected tracked-channel action."""
        login = self.channel.component.values[0]
        if self._action == "color":
            result = await dispatch_channel_command(
                self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                action="color",
                twitch_channel_login=login,
                color=normalize_optional_text(self.color.value if self.color is not None else None),
                clear_color=normalize_optional_text(self.color.value if self.color is not None else None) is None,
            )
        else:
            result = await dispatch_channel_command(
                self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                action=self._action,
                twitch_channel_login=login,
            )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ChannelMenuView(BaseFormView):
    """Root `/channel` flow with button-based action selection."""

    def __init__(
        self,
        *,
        owner_id: int,
        event_bus: EventBus,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
        localizer: Localizer,
    ) -> None:
        super().__init__(
            owner_id=owner_id,
            localizer=localizer,
            language=resolve_context_language(
                localizer=localizer,
                data_provider=data_provider,
                discord_channel_id=discord_channel_id,
            ),
        )
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self.add.label = self.text("discord.channel_ui.actions.add")
        self.remove.label = self.text("discord.channel_ui.actions.remove")
        self.color.label = self.text("discord.channel_ui.actions.color")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.channel_ui.menu.title", "discord.channel_ui.menu.message")

    @discord.ui.button(label="Add", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            ChannelNameModal(
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action="add",
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_selection_modal(interaction, action="remove")

    @discord.ui.button(label="Color", style=discord.ButtonStyle.secondary)
    async def color(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_selection_modal(interaction, action="color")

    async def _open_selection_modal(self, interaction: discord.Interaction, *, action: str) -> None:
        tracked_channels = await self._data_provider.list_tracked_channels(self._discord_channel_id)
        if not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.channel_ui.errors.no_channels", style=DiscordResultStyle.ERROR),
            )
            return
        await interaction.response.send_modal(
            ChannelSelectionModal(
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action=action,
                tracked_channels=tracked_channels,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )
