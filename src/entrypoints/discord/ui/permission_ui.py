"""Discord UI for `/permission`."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.utils.permissions import PERMISSION_CHOICES

from ..dispatch import dispatch_clear_permissions, dispatch_grant_permissions, dispatch_revoke_permissions
from ..helpers import complete_bound_result
from ..ui_data import DiscordUIDataProvider
from .shared import BaseFormView, resolve_context_language


def _permission_option_label(*, localizer: Localizer, language: str, value: str) -> str:
    try:
        return localizer.text(f"show.permission.{value}", language=language)
    except ValueError:
        return value.replace("_", " ").capitalize()


class PermissionModal(discord.ui.Modal):
    """Manage one permission grant, revoke, or clear action from a modal."""

    def __init__(
        self,
        *,
        title: str,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.user = discord.ui.Label(
            text=localizer.text("discord.permission_ui.modal.user_label", language=language),
            component=discord.ui.UserSelect(min_values=1, max_values=1),
        )
        self.add_item(self.user)
        if action != "clear":
            self.permission = discord.ui.Label(
                text=localizer.text("discord.permission_ui.modal.permissions_label", language=language),
                component=discord.ui.Select(
                    options=[
                        discord.SelectOption(
                            label=_permission_option_label(localizer=localizer, language=language, value=value)[:100],
                            value=value,
                        )
                        for value, _ in PERMISSION_CHOICES[:25]
                    ],
                    min_values=1,
                    max_values=min(len(PERMISSION_CHOICES), 25),
                ),
            )
            self.add_item(self.permission)
        else:
            self.permission = None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch one permission-management action."""
        selected_user = self.user.component.values[0]
        permissions = () if self.permission is None else tuple(self.permission.component.values)
        if self._action == "grant":
            result = await dispatch_grant_permissions(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                target_user_id=selected_user.id,
                permissions=permissions,
            )
        elif self._action == "revoke":
            result = await dispatch_revoke_permissions(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                target_user_id=selected_user.id,
                permissions=permissions,
            )
        else:
            result = await dispatch_clear_permissions(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                target_user_id=selected_user.id,
            )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class PermissionMenuView(BaseFormView):
    """Root `/permission` flow with one button per action."""

    def __init__(
        self,
        *,
        owner_id: int,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        data_provider: DiscordUIDataProvider,
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
        self._discord_channel_id = discord_channel_id
        self.grant.label = self.text("discord.permission_ui.actions.grant")
        self.revoke.label = self.text("discord.permission_ui.actions.revoke")
        self.clear.label = self.text("discord.permission_ui.actions.clear")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.permission_ui.menu.title", "discord.permission_ui.menu.message")

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def grant(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_modal(interaction, "grant")

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def revoke(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_modal(interaction, "revoke")

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def clear(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_modal(interaction, "clear")

    async def _open_modal(self, interaction: discord.Interaction, action: str) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PERMISSION,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        await interaction.response.send_modal(
            PermissionModal(
                title=self.text(f"discord.permission_ui.modal.{action}.title"),
                services=self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action=action,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )
