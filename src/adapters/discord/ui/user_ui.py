from __future__ import annotations

"""Discord UI for `/user`."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.utils.discord_embeds import build_result_embed

from ..dispatch import dispatch_user_command
from ..helpers import complete_bound_result
from ..ui_data import DiscordUIDataProvider, TrackedUserPresentation
from .shared import BaseFormView, build_form_embed


class UserNameModal(discord.ui.Modal):
    """Simple modal used for adding tracked Twitch users."""

    twitch_name = discord.ui.TextInput(
        label="Twitch Name",
        placeholder="DanceDown",
        required=True,
    )

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title="Add User", timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        result = await dispatch_user_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action=self._action,
            twitch_user_login=self.twitch_name.value.strip(),
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class UserSelectionModal(discord.ui.Modal):
    """Select one tracked Twitch user for removal."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        tracked_users: list[TrackedUserPresentation],
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title="Remove User", timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        self.user = discord.ui.Label(
            text="Twitch user",
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=user.display_name[:100],
                        value=user.login,
                        description=user.login[:100],
                    )
                    for user in tracked_users[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.user)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        result = await dispatch_user_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action="remove",
            twitch_user_login=self.user.component.values[0],
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class UserMenuView(BaseFormView):
    """Root `/user` flow with button-based action selection."""

    def __init__(
        self,
        *,
        owner_id: int,
        event_bus: EventBus,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
    ) -> None:
        super().__init__(owner_id=owner_id)
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id

    def render_embed(self) -> discord.Embed:
        return build_form_embed(
            "Tracked Users",
            "Add or remove Twitch users",
        )

    @discord.ui.button(label="Add", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            UserNameModal(
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action="add",
                bound_message=self.bound_message,
            )
        )

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        tracked_users = await self._data_provider.list_tracked_users(self._discord_channel_id)
        if not tracked_users:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title="No Users",
                    message="There are no tracked Twitch users to remove.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(
            UserSelectionModal(
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                tracked_users=tracked_users,
                bound_message=self.bound_message,
            )
        )
