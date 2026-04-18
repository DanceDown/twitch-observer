from __future__ import annotations

"""Discord UI for `/channel`."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.utils.discord_embeds import build_result_embed

from ..dispatch import dispatch_channel_command
from ..helpers import complete_bound_result, normalize_optional_text, send_initial_result
from ..ui_data import DiscordUIDataProvider, TrackedChannelPresentation
from .shared import BaseFormView, build_form_embed


class ChannelNameModal(discord.ui.Modal):
    """Simple modal used for adding tracked Twitch channels."""

    channel_name = discord.ui.TextInput(
        label="Twitch Name",
        placeholder="DanceDown",
        required=True,
    )

    def __init__(
        self,
        *,
        title: str,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message

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
        title: str,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        tracked_channels: list[TrackedChannelPresentation],
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.channel = discord.ui.Label(
            text="Tracked Channel",
            description="Choose a Twitch channel.",
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
                label="Color",
                placeholder="e.g. #9146FF",
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
    ) -> None:
        super().__init__(owner_id=owner_id)
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id

    def render_embed(self) -> discord.Embed:
        return build_form_embed(
            "Channels",
            "Add, remove or recolor Twitch channels.",
        )

    @discord.ui.button(label="Add", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            ChannelNameModal(
                title="Add Channel",
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action="add",
                bound_message=self.bound_message,
            )
        )

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_selection_modal(interaction, action="remove", title="Remove Channel")

    @discord.ui.button(label="Color", style=discord.ButtonStyle.secondary)
    async def color(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_selection_modal(interaction, action="color", title="Channel Color")

    async def _open_selection_modal(self, interaction: discord.Interaction, *, action: str, title: str) -> None:
        tracked_channels = await self._data_provider.list_tracked_channels(self._discord_channel_id)
        if not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title="No Channels Available",
                    message="There are no Twitch channels available to modify.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(
            ChannelSelectionModal(
                title=title,
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action=action,
                tracked_channels=tracked_channels,
                bound_message=self.bound_message,
            )
        )
