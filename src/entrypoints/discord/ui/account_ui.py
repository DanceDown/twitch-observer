"""Discord UI for `/account`."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_start_account_link, dispatch_unlink_account
from ..ui_data import DiscordUIDataProvider
from .shared import BaseFormView, resolve_context_language


class AccountMenuView(BaseFormView):
    """Root `/account` flow with one button per action."""

    def __init__(
        self,
        *,
        owner_id: int,
        services: DiscordServiceBundle,
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
        self._services = services
        self._discord_channel_id = discord_channel_id
        self.link.label = self.text("discord.account_ui.actions.connect")
        self.unlink.label = self.text("discord.account_ui.actions.disconnect")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.account_ui.menu.title", "discord.account_ui.menu.message")

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def link(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "link")

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def unlink(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "unlink")

    async def _run(self, interaction: discord.Interaction, action: str) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.ACCOUNT,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        if action == "link":
            result = await dispatch_start_account_link(
                self._services,
                requester_id=interaction.user.id,
                discord_channel_id=self._discord_channel_id,
            )
        else:
            result = await dispatch_unlink_account(
                self._services,
                requester_id=interaction.user.id,
                discord_channel_id=self._discord_channel_id,
            )
        await self.finish_with_interaction(interaction, result)
