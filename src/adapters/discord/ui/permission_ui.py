from __future__ import annotations

"""Discord UI for `/permission`."""

import discord

from src.events.event_bus import EventBus
from src.utils.permissions import PERMISSION_CHOICES

from ..dispatch import dispatch_permission_command
from ..helpers import complete_bound_result
from .shared import BaseFormView, build_form_embed


class PermissionModal(discord.ui.Modal):
    """Manage one permission grant, revoke, or clear action from a modal."""

    def __init__(
        self,
        *,
        title: str,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.user = discord.ui.Label(
            text="Discord User",
            component=discord.ui.UserSelect(min_values=1, max_values=1),
        )
        self.add_item(self.user)
        if action != "clear":
            self.permission = discord.ui.Label(
                text="Permissions",
                component=discord.ui.Select(
                    options=[
                        discord.SelectOption(label=value[:100], value=value)
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
        result = await dispatch_permission_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action=self._action,
            target_user_id=selected_user.id,
            permissions=None if self.permission is None else tuple(self.permission.component.values),
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class PermissionMenuView(BaseFormView):
    """Root `/permission` flow with one button per action."""

    def __init__(self, *, owner_id: int, event_bus: EventBus, discord_channel_id: int) -> None:
        super().__init__(owner_id=owner_id)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id

    def render_embed(self) -> discord.Embed:
        return build_form_embed(
            "Permissions",
            "Grant a permission, revoke one, or clear all permissions for a Discord user.",
        )

    @discord.ui.button(label="Grant", style=discord.ButtonStyle.primary)
    async def grant(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_modal(interaction, "grant")

    @discord.ui.button(label="Revoke", style=discord.ButtonStyle.secondary)
    async def revoke(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_modal(interaction, "revoke")

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.secondary)
    async def clear(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_modal(interaction, "clear")

    async def _open_modal(self, interaction: discord.Interaction, action: str) -> None:
        await interaction.response.send_modal(
            PermissionModal(
                title=f"{action.capitalize()} Permission",
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action=action,
                bound_message=self.bound_message,
            )
        )
