"""User-scope modal for the guided ping editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from ...ui_data import TrackedUserPresentation
from ..selects import window_with_included_items

if TYPE_CHECKING:
    from .home import PatternHomeView


class PatternUsersModal(discord.ui.Modal):
    """Collect one user-scope update for one ping."""

    def __init__(self, *, parent: PatternHomeView, tracked_users: list[TrackedUserPresentation]) -> None:
        super().__init__(title=parent.text("discord.pattern_ui.users.title"), timeout=300)
        self._parent_view = parent
        self._tracked_users = tracked_users
        visible_users = window_with_included_items(
            tracked_users,
            key=lambda user: user.login,
            included_keys=parent.state.selected_users,
        )
        self.scope = discord.ui.Label(
            text=parent.text("discord.pattern_ui.users.scope_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_everyone"),
                        value="all_users",
                        default=parent.state.user_scope_mode == "all_users",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_all_tracked"),
                        value="all_tracked",
                        default=parent.state.user_scope_mode == "all_tracked",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_all_tracked_except"),
                        value="all_tracked_except_selected",
                        default=parent.state.user_scope_mode == "all_tracked_except_selected",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_only"),
                        value="only_selected",
                        default=parent.state.user_scope_mode == "only_selected",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_everyone_except"),
                        value="all_except_selected",
                        default=parent.state.user_scope_mode == "all_except_selected",
                    ),
                ]
            ),
        )
        self.users = discord.ui.Label(
            text=parent.text("discord.pattern_ui.users.tracked_label"),
            description=parent.text("discord.pattern_ui.users.tracked_description"),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=user.display_name[:100],
                        value=user.login,
                        description=user.login[:100],
                        default=user.login in parent.state.selected_users,
                    )
                    for user in visible_users
                ],
                min_values=1,
                max_values=min(len(visible_users), 25),
                required=False,
            ),
        )
        self.add_item(self.scope)
        self.add_item(self.users)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = self._parent_view.state
        state.user_scope_mode = self.scope.component.value
        if state.user_scope_mode in {"all_users", "all_tracked"}:
            state.selected_users.clear()
            state.selected_user_names.clear()
        elif self.users.component.values:
            state.selected_users = list(self.users.component.values)
            name_by_login = {user.login: user.display_name for user in self._tracked_users}
            state.selected_user_names = [name_by_login.get(login, login) for login in state.selected_users]
        await interaction.response.defer()
        await self._parent_view.rerender()
