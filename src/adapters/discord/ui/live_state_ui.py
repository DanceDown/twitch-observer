from __future__ import annotations

"""Discord UI for configuring tracked Twitch live/offline notifications."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle

from ..dispatch import dispatch_channel_event_command
from ..helpers import complete_bound_result, send_initial_result
from ..ui_data import DiscordUIDataProvider, TrackedChannelPresentation


class ChannelEventModal(discord.ui.Modal):
    """Choose one tracked channel and configure one external channel event."""

    def __init__(
        self,
        *,
        title: str,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        tracked_channels: list[TrackedChannelPresentation],
        event_key: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._event_key = event_key
        self._bound_message = bound_message
        state_text = "live" if event_key == "stream.online" else "offline"
        self.channel = discord.ui.Label(
            text="Tracked Channel",
            description=f"Choose the tracked Twitch channel that should trigger a Discord notification when it goes {state_text}.",
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
        result = await dispatch_channel_event_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            twitch_channel_id=self.channel.component.values[0],
            event_key=self._event_key,
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


async def open_channel_event_modal(
    interaction: discord.Interaction,
    *,
    title: str,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    event_key: str,
) -> None:
    """Resolve tracked channels and open the event-notification modal."""
    if interaction.channel_id is None:
        await send_initial_result(
            interaction,
            DiscordCommandResult(
                title="Command Unavailable",
                message="This command can only be used inside a Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            ),
        )
        return

    tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
    if not tracked_channels:
        await send_initial_result(
            interaction,
            DiscordCommandResult(
                title="No Channels Available",
                message="Track a Twitch channel first before configuring live or offline notifications.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            ),
        )
        return

    await interaction.response.send_modal(
        ChannelEventModal(
            title=title,
            event_bus=event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            tracked_channels=tracked_channels,
            event_key=event_key,
        )
    )
