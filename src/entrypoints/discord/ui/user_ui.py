"""Discord UI for `/user`."""

from __future__ import annotations

import discord

from ..dispatch import dispatch_add_tracked_user, dispatch_remove_tracked_user
from ..helpers import complete_bound_result, defer_interaction_response
from ..ui_data import TrackedUserPresentation
from .selects import window_with_included_items
from .shared import DiscordModalContext


class UserNameModal(discord.ui.Modal):
    """Simple modal used for adding tracked Twitch users."""

    def __init__(
        self,
        *,
        context: DiscordModalContext,
    ) -> None:
        """Create the modal for entering a Twitch user login."""
        super().__init__(
            title=context.localizer.text("discord.user_ui.modal.add.title", language=context.language),
            timeout=300,
        )
        self._context = context
        self.twitch_name = discord.ui.TextInput(
            label=context.localizer.text("discord.user_ui.modal.add.name_label", language=context.language),
            placeholder=context.localizer.text("discord.user_ui.modal.add.name_placeholder", language=context.language),
            required=True,
        )
        self.add_item(self.twitch_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the entered Twitch user as a tracked-user add command."""
        await defer_interaction_response(interaction, ephemeral=True)
        result = await dispatch_add_tracked_user(
            self._context.services,
            discord_channel_id=self._context.discord_channel_id,
            requester_id=self._context.requester_id,
            twitch_user_login=self.twitch_name.value.strip(),
        )
        await complete_bound_result(interaction, bound_message=self._context.bound_message, result=result)


class UserSelectionModal(discord.ui.Modal):
    """Select one tracked Twitch user for removal."""

    def __init__(
        self,
        *,
        context: DiscordModalContext,
        tracked_users: list[TrackedUserPresentation],
        default_login: str | None = None,
    ) -> None:
        """Create the modal for selecting a tracked user to remove."""
        super().__init__(
            title=context.localizer.text("discord.user_ui.modal.remove.title", language=context.language),
            timeout=300,
        )
        self._context = context
        visible_users = window_with_included_items(
            tracked_users,
            key=lambda user: user.login,
            included_keys=[default_login] if default_login else [],
        )
        self.user = discord.ui.Label(
            text=context.localizer.text("discord.user_ui.modal.remove.user_label", language=context.language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=user.display_name[:100],
                        value=user.login,
                        description=user.login[:100],
                        default=user.login == default_login,
                    )
                    for user in visible_users
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.user)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the selected Twitch user as a tracked-user remove command."""
        await defer_interaction_response(interaction, ephemeral=True)
        result = await dispatch_remove_tracked_user(
            self._context.services,
            discord_channel_id=self._context.discord_channel_id,
            requester_id=self._context.requester_id,
            twitch_user_login=self.user.component.values[0],
        )
        await complete_bound_result(interaction, bound_message=self._context.bound_message, result=result)
