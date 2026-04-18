from __future__ import annotations

"""Discord UI for `/account`."""

import discord

from src.events.event_bus import EventBus

from ..dispatch import dispatch_account_command
from .shared import BaseFormView, build_form_embed


class AccountMenuView(BaseFormView):
    """Root `/account` flow with one button per action."""

    def __init__(self, *, owner_id: int, event_bus: EventBus, discord_channel_id: int | None) -> None:
        super().__init__(owner_id=owner_id)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id

    def render_embed(self) -> discord.Embed:
        return build_form_embed(
            "Twitch Account",
            "Choose whether you want to connect or disconnect your Twitch account.",
        )

    @discord.ui.button(label="Connect", style=discord.ButtonStyle.primary)
    async def link(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "link")

    @discord.ui.button(label="Disconnect", style=discord.ButtonStyle.secondary)
    async def unlink(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "unlink")

    @discord.ui.button(label="Show", style=discord.ButtonStyle.secondary)
    async def show(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "show")

    async def _run(self, interaction: discord.Interaction, action: str) -> None:
        result = await dispatch_account_command(
            self._event_bus,
            requester_id=interaction.user.id,
            discord_channel_id=self._discord_channel_id,
            action=action,
        )
        await self.finish_with_interaction(interaction, result)
