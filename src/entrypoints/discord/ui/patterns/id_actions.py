"""ID-based ping action views and selection modals."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer

from ...dispatch import dispatch_disable_pattern, dispatch_enable_pattern, dispatch_remove_pattern
from ...ui_data import DiscordUIDataProvider, PatternPresentation
from ..shared import BaseFormView, resolve_context_language
from .state import PatternActionKind


class PatternIdActionView(BaseFormView):
    """Simple parameterless flows for ping remove/enable/disable actions."""

    def __init__(
        self,
        *,
        owner_id: int,
        services: DiscordServiceBundle,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
        action: PatternActionKind,
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
        self._action = action
        self._patterns: list[PatternPresentation] = []

    async def prepare(self) -> DiscordCommandResult | None:
        patterns = await self._data_provider.list_patterns(self._discord_channel_id)
        if self._action is PatternActionKind.DISABLE:
            patterns = [pattern for pattern in patterns if not pattern.pattern.disabled]
        elif self._action is PatternActionKind.ENABLE:
            patterns = [pattern for pattern in patterns if pattern.pattern.disabled]
        self._patterns = patterns
        if self._patterns:
            return None
        return DiscordCommandResult(
            title={
                PatternActionKind.DISABLE: self.text("discord.pattern_ui.errors.no_enabled.title"),
                PatternActionKind.ENABLE: self.text("discord.pattern_ui.errors.no_disabled.title"),
            }.get(self._action, self.text("discord.pattern_ui.errors.no_pings.title")),
            message={
                PatternActionKind.DISABLE: self.text("discord.pattern_ui.errors.no_enabled.message"),
                PatternActionKind.ENABLE: self.text("discord.pattern_ui.errors.no_disabled.message"),
            }.get(self._action, self.text("discord.pattern_ui.errors.no_pings.message")),
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )

    def render_embed(self) -> discord.Embed:
        action_label = {
            PatternActionKind.REMOVE: self.text("discord.pattern_ui.action.remove_title"),
            PatternActionKind.DISABLE: self.text("discord.pattern_ui.action.disable_title"),
            PatternActionKind.ENABLE: self.text("discord.pattern_ui.action.enable_title"),
        }.get(self._action, self.text("discord.pattern_ui.action.manage_title"))
        return self.form_embed(
            "discord.pattern_ui.action.embed_title",
            "discord.pattern_ui.action.embed_message",
            ACTION=action_label,
        )

    async def run_action(self, interaction: discord.Interaction, pattern_id: int) -> None:
        if self._action is PatternActionKind.REMOVE:
            result = await dispatch_remove_pattern(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                pattern_id=pattern_id,
            )
        elif self._action is PatternActionKind.DISABLE:
            result = await dispatch_disable_pattern(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                pattern_id=pattern_id,
            )
        else:
            result = await dispatch_enable_pattern(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                pattern_id=pattern_id,
            )
        await self.finish_with_interaction(interaction, result)


class PatternActionSelectionModal(discord.ui.Modal):
    """Choose one ping to remove, enable, or disable."""

    def __init__(
        self,
        *,
        title: str,
        parent: PatternIdActionView,
        patterns: list[PatternPresentation],
        localizer: Localizer,
        language: str,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._parent_view = parent
        self.pattern = discord.ui.Label(
            text=localizer.text("discord.pattern_ui.selection.update_label", language=language),
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
        await self._parent_view.run_action(interaction, int(self.pattern.component.values[0]))
