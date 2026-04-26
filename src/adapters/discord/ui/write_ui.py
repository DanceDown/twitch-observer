from __future__ import annotations

"""Discord UI for `/write`."""

import discord

from src.events.event_bus import EventBus
from src.localization import Localizer

from ..dispatch import dispatch_write_command
from ..helpers import normalize_optional_text, send_initial_result
from ..ui_data import TrackedChannelPresentation


class WriteModal(discord.ui.Modal):
    """Send one manual Twitch message from inside Discord."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        tracked_channels: list[TrackedChannelPresentation],
        localizer: Localizer,
        language: str,
    ) -> None:
        super().__init__(title=localizer.text("discord.write_ui.modal.title", language=language), timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self.message = discord.ui.TextInput(
            label=localizer.text("discord.write_ui.modal.message_label", language=language),
            style=discord.TextStyle.paragraph,
            placeholder=localizer.text("discord.write_ui.modal.message_placeholder", language=language),
            required=True,
            max_length=500,
        )
        self.reply_to = discord.ui.TextInput(
            label=localizer.text("discord.write_ui.modal.reply_to_label", language=language),
            placeholder=localizer.text("discord.write_ui.modal.reply_to_placeholder", language=language),
            required=False,
        )
        self.channel = discord.ui.Label(
            text=localizer.text("discord.write_ui.modal.channel_label", language=language),
            description=localizer.text("discord.write_ui.modal.channel_description", language=language),
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
        self.add_item(self.message)
        self.add_item(self.reply_to)
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
