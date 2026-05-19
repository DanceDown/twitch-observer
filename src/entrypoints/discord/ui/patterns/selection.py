"""Edit-selection view and modal for the guided ping editor."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.utils.discord_embeds import build_result_embed

from ...ui_data import DiscordUIDataProvider, PatternPresentation
from ..shared import BaseFormView, resolve_context_language
from .home import PatternHomeView
from .state import PatternEditorMode, PatternFormState


class PatternPickerView(BaseFormView):
    """First-step pattern picker that opens the full edit wizard."""

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
        self._patterns: list[PatternPresentation] = []

    async def prepare(self) -> DiscordCommandResult | None:
        self._patterns = await self._data_provider.list_patterns(self._discord_channel_id)
        if self._patterns:
            return None
        return DiscordCommandResult(
            title=self.text("discord.pattern_ui.errors.no_pings.title"),
            message=self.text("discord.pattern_ui.errors.no_pings.message"),
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.pattern_ui.edit.title", "discord.pattern_ui.edit.message")

    async def submit_selection(self, interaction: discord.Interaction, pattern_id: int) -> None:
        pattern = await self._data_provider.get_pattern(self._discord_channel_id, pattern_id)
        if pattern is None:
            await interaction.response.defer()
            if self.bound_message is not None:
                await self.bound_message.edit(
                    embed=build_result_embed(
                        DiscordCommandResult(
                            title=self.text("discord.pattern_ui.errors.not_found.title"),
                            message=self.text("discord.pattern_ui.errors.not_found.message"),
                            style=DiscordResultStyle.ERROR,
                            ephemeral=True,
                        )
                    ),
                    view=None,
                )
            return
        state = PatternFormState(
            pattern_id=pattern.pattern.pattern_id,
            pattern_text=pattern.pattern.regex,
            is_regex=pattern.pattern.is_regex,
            channel_scope_mode=pattern.pattern.channel_scope_mode,
            selected_channels=list(pattern.channel_logins),
            selected_channel_names=list(pattern.channel_display_names),
            user_scope_mode=pattern.pattern.user_scope_mode,
            selected_users=list(pattern.user_logins),
            selected_user_names=list(pattern.user_display_names),
            sub_state=pattern.pattern.sub_state,
            offline_state=pattern.pattern.offline_state,
            case_sensitive=pattern.pattern.case_sensitive,
            color=pattern.pattern.color,
            priority=pattern.pattern.priority,
        )
        view = PatternHomeView(
            owner_id=self.owner_id,
            services=self._services,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            mode=PatternEditorMode.EDIT,
            state=state,
            localizer=self._localizer,
        )
        view.bound_message = self.bound_message
        await interaction.response.defer()
        if self.bound_message is not None:
            await self.bound_message.edit(embed=view.render_embed(), view=view)


class PatternEditSelectionModal(discord.ui.Modal):
    """Choose one existing ping and then open the edit wizard."""

    def __init__(
        self,
        *,
        parent: PatternPickerView,
        patterns: list[PatternPresentation],
        localizer: Localizer,
        language: str,
    ) -> None:
        super().__init__(title=localizer.text("discord.pattern_ui.selection.choose_title", language=language), timeout=300)
        self._parent_view = parent
        self.pattern = discord.ui.Label(
            text=localizer.text("discord.pattern_ui.selection.edit_label", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=(item.pattern.regex or localizer.text("discord.pattern_ui.selection.untitled_ping", language=language))[:100],
                        value=str(item.pattern.pattern_id),
                        description=localizer.text(
                            "discord.pattern_ui.selection.option_description",
                            language=language,
                            ID=item.display_index,
                            TYPE=localizer.text(
                                (
                                    "discord.pattern_ui.summary.mode_regex"
                                    if item.pattern.is_regex
                                    else "discord.pattern_ui.summary.mode_ping"
                                ),
                                language=language,
                            ),
                        ),
                    )
                    for item in patterns[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.pattern)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._parent_view.submit_selection(interaction, int(self.pattern.component.values[0]))
