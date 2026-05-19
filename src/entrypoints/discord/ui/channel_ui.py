"""Discord UI for `/channel`."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_add_tracked_channel, dispatch_remove_tracked_channel, dispatch_set_tracked_channel_color
from ..helpers import complete_bound_result, normalize_optional_text
from ..ui_data import DiscordUIDataProvider, TrackedChannelPresentation
from .shared import BaseFormView, resolve_context_language


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


class ChannelMenuView(BaseFormView):
    """Root `/channel` flow with button-based action selection."""

    def __init__(
        self,
        *,
        owner_id: int,
        services: DiscordServiceBundle,
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
        self._services = services
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self.add.label = self.text("discord.channel_ui.actions.add")
        self.remove.label = self.text("discord.channel_ui.actions.remove")
        self.color.label = self.text("discord.channel_ui.actions.color")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.channel_ui.menu.title", "discord.channel_ui.menu.message")

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.CHANNEL,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        await interaction.response.send_modal(
            ChannelNameModal(
                services=self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action="add",
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_selection_modal(interaction, action="remove")

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def color(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_selection_modal(interaction, action="color")

    async def _open_selection_modal(self, interaction: discord.Interaction, *, action: str) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.CHANNEL,
            step=UIFlowStep.REMOVE if action == "remove" else UIFlowStep.COLOR,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        tracked_channels = await self._data_provider.list_tracked_channels(self._discord_channel_id)
        if not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.channel_ui.errors.no_channels", style=DiscordResultStyle.ERROR),
            )
            return
        await interaction.response.send_modal(
            ChannelSelectionModal(
                services=self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action=action,
                tracked_channels=tracked_channels,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )
