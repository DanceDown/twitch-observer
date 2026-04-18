from __future__ import annotations

"""Discord UI for thread-level observer commands."""

from contextlib import suppress

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle

from ..dispatch import dispatch_thread_command
from ..helpers import normalize_optional_text, send_initial_result


class LeaveConfirmationModal(discord.ui.Modal, title="Confirm Leave"):
    """Require an explicit confirmation phrase before deleting one Discord context."""

    confirmation = discord.ui.TextInput(
        label="Type LEAVE to confirm",
        placeholder="LEAVE",
        required=True,
        min_length=5,
        max_length=5,
    )

    def __init__(self, *, event_bus: EventBus, discord_channel_id: int, requester_id: int) -> None:
        super().__init__(timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate the confirmation phrase and dispatch the destructive leave action."""
        if self.confirmation.value.strip().upper() != "LEAVE":
            await send_initial_result(
                interaction,
                DiscordCommandResult(
                    title="Leave Cancelled",
                    message="Type exactly `LEAVE` if you want the bot to leave this Discord channel.",
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


class ThreadColorModal(discord.ui.Modal, title="Observer Color"):
    """Set or clear the default embed color for one Discord context."""

    color = discord.ui.TextInput(
        label="Color",
        placeholder="#5865F2",
        required=False,
    )

    def __init__(self, *, event_bus: EventBus, discord_channel_id: int, requester_id: int) -> None:
        super().__init__(timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id

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
