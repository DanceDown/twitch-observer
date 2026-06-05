"""Channel-scope modal for the guided ping editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from ...ui_data import TrackedChannelPresentation
from ..selects import window_with_included_items

if TYPE_CHECKING:
    from .home import PatternHomeView


class PatternChannelsModal(discord.ui.Modal):
    """Collect the Twitch-channel scope for one ping."""

    def __init__(self, *, parent: PatternHomeView, tracked_channels: list[TrackedChannelPresentation]) -> None:
        super().__init__(title=parent.text("discord.pattern_ui.channels.title"), timeout=300)
        self._parent_view = parent
        self._tracked_channels = tracked_channels
        visible_channels = window_with_included_items(
            tracked_channels,
            key=lambda channel: channel.login,
            included_keys=parent.state.selected_channels,
        )
        self.scope = discord.ui.Label(
            text=parent.text("discord.pattern_ui.channels.scope_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.channels.scope_all"),
                        value="all_tracked",
                        default=parent.state.channel_scope_mode == "all_tracked",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.channels.scope_only"),
                        value="only_selected",
                        default=parent.state.channel_scope_mode == "only_selected",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.channels.scope_except"),
                        value="all_except_selected",
                        default=parent.state.channel_scope_mode == "all_except_selected",
                    ),
                ]
            ),
        )
        self.channels = discord.ui.Label(
            text=parent.text("discord.pattern_ui.channels.tracked_label"),
            description=parent.text("discord.pattern_ui.channels.tracked_description"),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.login,
                        description=channel.login[:100],
                        default=channel.login in parent.state.selected_channels,
                    )
                    for channel in visible_channels
                ],
                min_values=1,
                max_values=min(len(visible_channels), 25),
                required=False,
            ),
        )
        self.add_item(self.scope)
        self.add_item(self.channels)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._parent_view.state.channel_scope_mode = self.scope.component.value
        if self.scope.component.value == "all_tracked":
            self._parent_view.state.selected_channels.clear()
            self._parent_view.state.selected_channel_names.clear()
        elif self.channels.component.values:
            self._parent_view.state.selected_channels = list(self.channels.component.values)
            name_by_login = {channel.login: channel.display_name for channel in self._tracked_channels}
            self._parent_view.state.selected_channel_names = [
                name_by_login.get(login, login) for login in self._parent_view.state.selected_channels
            ]
        await interaction.response.defer()
        await self._parent_view.rerender()
