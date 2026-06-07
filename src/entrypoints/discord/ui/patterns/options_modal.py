"""Options modal for the guided ping editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from src.events.discord_results import DiscordResultStyle

from .state import PatternEditorMode

if TYPE_CHECKING:
    from .home import PatternHomeView


class PatternOptionsModal(discord.ui.Modal):
    """Collect the remaining non-text match options for one ping."""

    def __init__(self, *, parent: PatternHomeView) -> None:
        super().__init__(title=parent.text("discord.pattern_ui.options.title"), timeout=300)
        self._parent_view = parent
        self.sub_state = discord.ui.Label(
            text=parent.text("discord.pattern_ui.options.sub_state_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.sub_state_all"),
                        value="all",
                        default=parent.state.sub_state == "all",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.sub_state_subs"),
                        value="subs",
                        default=parent.state.sub_state == "subs",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.sub_state_non_subs"),
                        value="non_subs",
                        default=parent.state.sub_state == "non_subs",
                    ),
                ]
            ),
        )
        self.offline_state = discord.ui.Label(
            text=parent.text("discord.pattern_ui.options.offline_state_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.offline_state_both"),
                        value="both",
                        default=parent.state.offline_state == "both",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.offline_state_online"),
                        value="online",
                        default=parent.state.offline_state == "online",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.offline_state_offline"),
                        value="offline",
                        default=parent.state.offline_state == "offline",
                    ),
                ]
            ),
        )
        priority_default = "" if parent.state.priority is None else str(parent.state.priority)
        self.priority = discord.ui.TextInput(
            label=parent.text("discord.pattern_ui.options.priority_label"),
            placeholder=parent.text("discord.pattern_ui.options.priority_placeholder"),
            default=priority_default,
            required=False,
        )
        self.add_item(self.sub_state)
        self.add_item(self.offline_state)
        self.add_item(self.priority)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._parent_view.state.sub_state = self.sub_state.component.value
        self._parent_view.state.offline_state = self.offline_state.component.value
        normalized = self.priority.value.strip()
        if normalized:
            try:
                parsed = int(normalized)
            except ValueError:
                await self._parent_view.finish_with_interaction(
                    interaction,
                    self._parent_view.result(
                        "discord.pattern_ui.errors.invalid_priority",
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )
                return
            if parsed < 0 or parsed > 9:
                await self._parent_view.finish_with_interaction(
                    interaction,
                    self._parent_view.result(
                        "discord.pattern_ui.errors.invalid_priority",
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )
                return
            self._parent_view.state.priority = parsed
        elif self._parent_view.mode is PatternEditorMode.EDIT:
            self._parent_view.state.priority = None
        await interaction.response.defer()
        await self._parent_view.rerender()
