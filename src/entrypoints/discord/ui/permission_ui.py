"""Discord UI for `/permission`."""

from __future__ import annotations

import discord
from discord import Object

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.localization import Localizer
from src.utils.permissions import PERMISSION_CHOICES

from ..dispatch import dispatch_clear_permissions, dispatch_grant_permissions, dispatch_revoke_permissions
from ..helpers import complete_bound_result, defer_interaction_response


def _permission_option_label(*, localizer: Localizer, language: str, value: str) -> str:
    return localizer.text(f"discord.permission_ui.modal.permission_label.{value}", language=language)


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
        default_user_id: int | None = None,
        default_permissions: tuple[str, ...] = (),
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
            component=discord.ui.UserSelect(
                min_values=1,
                max_values=1,
                default_values=([discord.SelectDefaultValue.from_user(Object(id=default_user_id))] if default_user_id is not None else []),
            ),
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
                            default=value in default_permissions,
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
        await defer_interaction_response(interaction, ephemeral=True)
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
