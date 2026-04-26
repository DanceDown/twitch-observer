from __future__ import annotations

"""Discord UI for `/account`."""

import discord

from src.events.event_bus import EventBus
from src.localization import Localizer

from ..dispatch import dispatch_account_command
from ..ui_data import DiscordUIDataProvider
from .shared import BaseFormView, resolve_context_language


class AccountMenuView(BaseFormView):
    """Root `/account` flow with one button per action."""

    def __init__(
        self,
        *,
        owner_id: int,
        event_bus: EventBus,
        discord_channel_id: int | None,
        data_provider: DiscordUIDataProvider,
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
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self.link.label = self.text("discord.account_ui.actions.connect")
        self.unlink.label = self.text("discord.account_ui.actions.disconnect")
        self.show.label = self.text("discord.account_ui.actions.show")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.account_ui.menu.title", "discord.account_ui.menu.message")

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
