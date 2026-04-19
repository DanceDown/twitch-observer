from __future__ import annotations

"""Discord UI for manual tracked-channel live/offline state changes."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle

from ..dispatch import dispatch_channel_live_state_command
from ..helpers import complete_bound_result, send_initial_result
from ..ui_data import DiscordUIDataProvider, TrackedChannelPresentation


class ChannelLiveStateModal(discord.ui.Modal):
    """Choose one tracked channel and persist its live/offline state."""

    def __init__(
        self,
        *,
        title: str,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        tracked_channels: list[TrackedChannelPresentation],
        is_live: bool,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._is_live = is_live
        self._bound_message = bound_message
        self.channel = discord.ui.Label(
            text="Tracked Channel",
            description="Choose the tracked Twitch channel whose live state should be updated.",
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.user_id,
                        description=channel.login[:100],
                    )
                    for channel in tracked_channels[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        result = await dispatch_channel_live_state_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            twitch_channel_id=self.channel.component.values[0],
            is_live=self._is_live,
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


async def open_channel_live_state_modal(
    interaction: discord.Interaction,
    *,
    title: str,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    is_live: bool,
) -> None:
    """Resolve tracked channels and open the manual live/offline modal."""
    if interaction.channel_id is None:
        await send_initial_result(interaction, DiscordCommandResult(
            title="Command Unavailable",
            message="This command can only be used inside a Discord channel.",
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        ))
        return

    tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
    if not tracked_channels:
        await send_initial_result(
            interaction,
            DiscordCommandResult(
                title="No Channels Available",
                message="Track a Twitch channel first before changing its live state.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            ),
        )
        return

    await interaction.response.send_modal(
        ChannelLiveStateModal(
            title=title,
            event_bus=event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            tracked_channels=tracked_channels,
            is_live=is_live,
        )
    )
