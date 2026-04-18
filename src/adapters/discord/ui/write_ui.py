from __future__ import annotations

"""Discord UI for `/write`."""

import discord

from src.events.event_bus import EventBus

from ..dispatch import dispatch_write_command
from ..helpers import normalize_optional_text, send_initial_result
from ..ui_data import TrackedChannelPresentation


class WriteModal(discord.ui.Modal, title="Write to Twitch"):
    """Send one manual Twitch message from inside Discord."""

    message = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        placeholder="Hello Twitch!",
        required=True,
        max_length=500,
    )
    reply_to = discord.ui.TextInput(
        label="Reply to",
        placeholder="Optional message ID",
        required=False,
    )

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        tracked_channels: list[TrackedChannelPresentation],
    ) -> None:
        super().__init__(timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self.channel = discord.ui.Label(
            text="Twitch Channel",
            description="Choose where the message should be sent.",
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

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch one manual Twitch send request."""
        result = await dispatch_write_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            twitch_channel_login=self.channel.component.values[0],
            message=self.message.value.strip(),
            reply_parent_message_id=normalize_optional_text(self.reply_to.value),
        )
        await send_initial_result(interaction, result)
