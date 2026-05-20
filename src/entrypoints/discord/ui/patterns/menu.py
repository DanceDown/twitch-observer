"""Root menu view for the guided ping flow."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ...ui_data import DiscordUIDataProvider
from ..shared import BaseFormView, resolve_context_language
from .home import PatternHomeView
from .id_actions import PatternActionSelectionModal, PatternIdActionView
from .selection import PatternEditSelectionModal, PatternPickerView
from .state import PatternActionKind, PatternEditorMode


class PingMenuView(BaseFormView):
    """Root `/ping` flow routing into add/edit/remove/enable/disable paths."""

    def __init__(
        self,
        *,
        owner_id: int,
        services: DiscordServiceBundle,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
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
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self.add.label = self.text("discord.pattern_ui.actions.add")
        self.edit.label = self.text("discord.pattern_ui.actions.edit")
        self.remove.label = self.text("discord.pattern_ui.actions.remove")
        self.disable.label = self.text("discord.pattern_ui.actions.disable")
        self.enable.label = self.text("discord.pattern_ui.actions.enable")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.pattern_ui.menu")

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ADD_PATTERN,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        view = PatternHomeView(
            owner_id=self.owner_id,
            services=self._services,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            mode=PatternEditorMode.ADD,
            localizer=self._localizer,
        )
        view.bound_message = self.bound_message
        await interaction.response.edit_message(embed=view.render_embed(), view=view)

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        view = PatternPickerView(
            owner_id=self.owner_id,
            services=self._services,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            localizer=self._localizer,
        )
        prepare_result = await view.prepare()
        if prepare_result is not None:
            await self.finish_with_interaction(interaction, prepare_result)
            return
        view.bound_message = self.bound_message
        await interaction.response.send_modal(
            PatternEditSelectionModal(
                parent=view,
                patterns=view._patterns,
                localizer=self._localizer,
                language=self.language,
            )
        )

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_id_action(interaction, PatternActionKind.REMOVE)

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def disable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_id_action(interaction, PatternActionKind.DISABLE)

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def enable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_id_action(interaction, PatternActionKind.ENABLE)

    async def _open_id_action(self, interaction: discord.Interaction, action: PatternActionKind) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PATTERN,
            step={
                PatternActionKind.REMOVE: UIFlowStep.REMOVE,
                PatternActionKind.DISABLE: UIFlowStep.DISABLE,
                PatternActionKind.ENABLE: UIFlowStep.ENABLE,
            }[action],
            discord_channel_id=self._discord_channel_id,
        ):
            return
        view = PatternIdActionView(
            owner_id=self.owner_id,
            services=self._services,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            action=action,
            localizer=self._localizer,
        )
        prepare_result = await view.prepare()
        if prepare_result is not None:
            await self.finish_with_interaction(interaction, prepare_result)
            return
        view.bound_message = self.bound_message
        await interaction.response.send_modal(
            PatternActionSelectionModal(
                title={
                    PatternActionKind.REMOVE: self.text("discord.pattern_ui.action.remove_title"),
                    PatternActionKind.DISABLE: self.text("discord.pattern_ui.action.disable_title"),
                    PatternActionKind.ENABLE: self.text("discord.pattern_ui.action.enable_title"),
                }.get(action, self.text("discord.pattern_ui.action.choose_title")),
                parent=view,
                patterns=view._patterns,
                localizer=self._localizer,
                language=self.language,
            )
        )
