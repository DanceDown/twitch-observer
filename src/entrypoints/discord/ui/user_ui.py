"""Discord UI for `/user`."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_add_tracked_user, dispatch_remove_tracked_user
from ..helpers import complete_bound_result
from ..ui_data import DiscordUIDataProvider, TrackedUserPresentation
from .shared import BaseFormView, resolve_context_language


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
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.user_ui.modal.remove.title", language=language), timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        self.user = discord.ui.Label(
            text=localizer.text("discord.user_ui.modal.remove.user_label", language=language),
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
        result = await dispatch_remove_tracked_user(
            self._services,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            twitch_user_login=self.user.component.values[0],
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class UserMenuView(BaseFormView):
    """Root `/user` flow with button-based action selection."""

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
        self.add.label = self.text("discord.user_ui.actions.add")
        self.remove.label = self.text("discord.user_ui.actions.remove")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.user_ui.menu")

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.USER,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        await interaction.response.send_modal(
            UserNameModal(
                services=self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action="add",
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.USER,
            step=UIFlowStep.REMOVE,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        tracked_users = await self._data_provider.list_tracked_users(self._discord_channel_id)
        if not tracked_users:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.user_ui.errors.no_users", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        await interaction.response.send_modal(
            UserSelectionModal(
                services=self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                tracked_users=tracked_users,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )
