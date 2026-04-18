from __future__ import annotations

"""Discord UI for `/show`."""

import discord

from src.events.event_bus import EventBus

from ..dispatch import dispatch_show_command
from ..helpers import send_initial_result


class ShowSectionModal(discord.ui.Modal, title="Show Configuration"):
    """Collect the requested `/show` section with a single modal."""

    def __init__(self, *, event_bus: EventBus, discord_channel_id: int, requester_id: int) -> None:
        super().__init__(timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self.section = discord.ui.Label(
            text="Section",
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(label="Pings", value="pings"),
                    discord.RadioGroupOption(label="Auto-Replies", value="auto_replies"),
                    discord.RadioGroupOption(label="Channels", value="channels", default=True),
                    discord.RadioGroupOption(label="Users", value="users"),
                    discord.RadioGroupOption(label="Permissions", value="permissions"),
                ]
            ),
        )
        self.add_item(self.section)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Render the selected overview section."""
        result = await dispatch_show_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            sections=(self.section.component.value or "channels",),
        )
        await send_initial_result(interaction, result)
