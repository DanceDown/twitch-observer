"""Discord UI for `/permission`."""

from __future__ import annotations

import discord
from discord import Object

from src.localization import Localizer
from src.utils.permissions import PERMISSION_CHOICES

from ..dispatch import dispatch_clear_permissions, dispatch_grant_permissions, dispatch_revoke_permissions
from ..helpers import complete_bound_result, defer_interaction_response
from .shared import DiscordModalContext


def _permission_option_label(*, localizer: Localizer, language: str, value: str) -> str:
    return localizer.text(f"discord.permission_ui.modal.permission_label.{value}", language=language)


class PermissionModal(discord.ui.Modal):
    """Manage one permission grant, revoke, or clear action from a modal."""

    def __init__(
        self,
        *,
        title: str,
        context: DiscordModalContext,
        action: str,
        default_user_id: int | None = None,
        default_permissions: tuple[str, ...] = (),
    ) -> None:
        """Create the modal for one permission action."""
        super().__init__(title=title, timeout=300)
        self._context = context
        self._action = action
        self.user = discord.ui.Label(
            text=context.localizer.text("discord.permission_ui.modal.user_label", language=context.language),
            component=discord.ui.UserSelect(
                min_values=1,
                max_values=1,
                default_values=([discord.SelectDefaultValue.from_user(Object(id=default_user_id))] if default_user_id is not None else []),
            ),
        )
        self.add_item(self.user)
        if action != "clear":
            self.permission = discord.ui.Label(
                text=context.localizer.text("discord.permission_ui.modal.permissions_label", language=context.language),
                component=discord.ui.Select(
                    options=[
                        discord.SelectOption(
                            label=_permission_option_label(
                                localizer=context.localizer,
                                language=context.language,
                                value=value,
                            )[:100],
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
                self._context.services,
                discord_channel_id=self._context.discord_channel_id,
                requester_id=self._context.requester_id,
                target_user_id=selected_user.id,
                permissions=permissions,
            )
        elif self._action == "revoke":
            result = await dispatch_revoke_permissions(
                self._context.services,
                discord_channel_id=self._context.discord_channel_id,
                requester_id=self._context.requester_id,
                target_user_id=selected_user.id,
                permissions=permissions,
            )
        else:
            result = await dispatch_clear_permissions(
                self._context.services,
                discord_channel_id=self._context.discord_channel_id,
                requester_id=self._context.requester_id,
                target_user_id=selected_user.id,
            )
        await complete_bound_result(interaction, bound_message=self._context.bound_message, result=result)
