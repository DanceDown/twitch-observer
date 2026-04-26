from __future__ import annotations

"""Discord UI for thread-level observer commands."""

from contextlib import suppress

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordResultStyle
from src.localization import Localizer

from ..dispatch import dispatch_thread_command
from ..helpers import normalize_optional_text, send_initial_result
from ..ui_data import DiscordUIDataProvider


class LeaveConfirmationModal(discord.ui.Modal):
    """Require an explicit confirmation phrase before deleting one Discord context."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        data_provider: DiscordUIDataProvider,
        localizer: Localizer,
    ) -> None:
        thread = data_provider.get_thread(discord_channel_id)
        language = localizer.language_for_thread(thread)
        super().__init__(
            title=localizer.text("discord.thread_modal.confirm_leave_title", language=language),
            timeout=300,
        )
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._localizer = localizer
        self._language = language
        self.confirmation = discord.ui.TextInput(
            label=localizer.text("discord.thread_modal.confirm_leave_label", language=language),
            placeholder=localizer.text("discord.thread_modal.confirm_leave_placeholder", language=language),
            required=True,
            min_length=5,
            max_length=5,
        )
        self.add_item(self.confirmation)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate the confirmation phrase and dispatch the destructive leave action."""
        if self.confirmation.value.strip() != self._localizer.text(
            "discord.thread_modal.confirm_leave_placeholder",
            language=self._language,
        ):
            await send_initial_result(
                interaction,
                self._localizer.result(
                    "discord.thread_modal.confirm_leave_cancelled",
                    language=self._language,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return

        result = await dispatch_thread_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action="leave",
        )
        await send_initial_result(interaction, result)
        if result.style == DiscordResultStyle.SUCCESS and isinstance(interaction.channel, discord.Thread):
            with suppress(discord.HTTPException, discord.Forbidden):
                await interaction.channel.leave()


class ThreadColorModal(discord.ui.Modal):
    """Set or clear the default embed color for one Discord context."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        data_provider: DiscordUIDataProvider,
        localizer: Localizer,
    ) -> None:
        thread = data_provider.get_thread(discord_channel_id)
        language = localizer.language_for_thread(thread)
        super().__init__(
            title=localizer.text("discord.thread_modal.observer_color_title", language=language),
            timeout=300,
        )
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self.color = discord.ui.TextInput(
            label=localizer.text("discord.thread_modal.observer_color_label", language=language),
            placeholder=localizer.text("discord.thread_modal.observer_color_placeholder", language=language),
            required=False,
        )
        self.add_item(self.color)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the chosen color update for the current thread."""
        result = await dispatch_thread_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action="color",
            color=normalize_optional_text(self.color.value),
            clear_color=normalize_optional_text(self.color.value) is None,
        )
        await send_initial_result(interaction, result)
