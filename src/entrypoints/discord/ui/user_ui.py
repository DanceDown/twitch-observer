"""Discord UI for `/user`."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.localization import Localizer

from ..dispatch import dispatch_add_tracked_user, dispatch_remove_tracked_user
from ..helpers import complete_bound_result, defer_interaction_response
from ..ui_data import TrackedUserPresentation
from .selects import window_with_included_items


class UserNameModal(discord.ui.Modal):
    """Simple modal used for adding tracked Twitch users."""

    def __init__(
        self,
        *,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.user_ui.modal.add.title", language=language), timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        self.twitch_name = discord.ui.TextInput(
            label=localizer.text("discord.user_ui.modal.add.name_label", language=language),
            placeholder=localizer.text("discord.user_ui.modal.add.name_placeholder", language=language),
            required=True,
        )
        self.add_item(self.twitch_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await defer_interaction_response(interaction, ephemeral=True)
        result = await dispatch_add_tracked_user(
            self._services,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            twitch_user_login=self.twitch_name.value.strip(),
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class UserSelectionModal(discord.ui.Modal):
    """Select one tracked Twitch user for removal."""

    def __init__(
        self,
        *,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        tracked_users: list[TrackedUserPresentation],
        localizer: Localizer,
        language: str,
        default_login: str | None = None,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.user_ui.modal.remove.title", language=language), timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        visible_users = window_with_included_items(
            tracked_users,
            key=lambda user: user.login,
            included_keys=[default_login] if default_login else [],
        )
        self.user = discord.ui.Label(
            text=localizer.text("discord.user_ui.modal.remove.user_label", language=language),
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
        await defer_interaction_response(interaction, ephemeral=True)
        result = await dispatch_remove_tracked_user(
            self._services,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            twitch_user_login=self.user.component.values[0],
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)
