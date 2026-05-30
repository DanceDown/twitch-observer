"""Basics modal for the guided ping editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .home import PatternHomeView


class PatternBasicsModal(discord.ui.Modal):
    """Collect text, mode, casing, and color in one modal."""

    def __init__(self, *, parent: PatternHomeView) -> None:
        super().__init__(title=parent.text("discord.pattern_ui.basics.title"), timeout=300)
        self._parent_view = parent
        self.pattern_text = discord.ui.TextInput(
            label=parent.text("discord.pattern_ui.basics.pattern_text_label"),
            placeholder=parent.text("discord.pattern_ui.basics.pattern_text_placeholder"),
            default=parent.state.pattern_text,
            required=True,
            style=discord.TextStyle.paragraph,
        )
        self.mode = discord.ui.Label(
            text=parent.text("discord.pattern_ui.basics.mode_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.mode_word"),
                        value="ping",
                        default=not parent.state.is_regex,
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.mode_regex"),
                        value="regex",
                        default=parent.state.is_regex,
                    ),
                ]
            ),
        )
        self.case_sensitive = discord.ui.Label(
            text=parent.text("discord.pattern_ui.basics.extra_options_label"),
            description=parent.text("discord.pattern_ui.basics.extra_options_description"),
            component=discord.ui.CheckboxGroup(
                required=False,
                options=[
                    discord.CheckboxGroupOption(
                        label=parent.text("discord.pattern_ui.basics.case_sensitive_option"),
                        value="case_sensitive",
                        default=parent.state.case_sensitive,
                    )
                ],
            ),
        )
        self.color = discord.ui.TextInput(
            label=parent.text("discord.pattern_ui.basics.color_label"),
            placeholder=parent.text("discord.pattern_ui.basics.color_placeholder"),
            default=parent.state.color,
            required=False,
        )
        self.add_item(self.pattern_text)
        self.add_item(self.mode)
        self.add_item(self.case_sensitive)
        self.add_item(self.color)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._parent_view.state.pattern_text = self.pattern_text.value.strip()
        self._parent_view.state.is_regex = self.mode.component.value == "regex"
        self._parent_view.state.case_sensitive = "case_sensitive" in self.case_sensitive.component.values
        color_value = self.color.value.strip()
        self._parent_view.state.color = color_value or None
        await interaction.response.defer()
        await self._parent_view.rerender()
