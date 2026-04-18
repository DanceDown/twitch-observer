from __future__ import annotations

"""Shared Discord UI primitives used across command-specific flows."""

from dataclasses import dataclass, field
from contextlib import suppress

import discord

from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.utils.discord_embeds import build_result_embed

COLOR_PICKER_URL = "https://htmlcolorcodes.com/color-picker/"


def build_form_embed(title: str, message: str) -> discord.Embed:
    """Render one neutral configuration embed used by interactive command forms."""
    return build_result_embed(
        DiscordCommandResult(
            title=title,
            message=message,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )
    )


async def start_form(
    interaction: discord.Interaction,
    *,
    view: BaseFormView,
) -> None:
    """Send the original ephemeral interaction response and bind the view message."""
    await interaction.response.send_message(embed=view.render_embed(), view=view, ephemeral=True)
    view.bound_message = await interaction.original_response()


def _build_public_actor_embed(result: DiscordCommandResult, actor_mention: str) -> discord.Embed:
    """Render one public result embed that names the Discord user who triggered it."""
    embed = build_result_embed(result)
    embed.description = f"{actor_mention} {result.message}"
    return embed


@dataclass(slots=True)
class PatternFormState:
    """Mutable in-memory state for the guided ping add/edit flow."""

    pattern_id: int | None = None
    pattern_text: str | None = None
    is_regex: bool = False
    channel_scope_mode: str = "all_tracked"
    selected_channels: list[str] = field(default_factory=list)
    user_scope_mode: str = "all_users"
    selected_users: list[str] = field(default_factory=list)
    sub_state: str = "all"
    offline_state: str = "both"
    case_sensitive: bool = False
    color: str | None = None
    priority: int | None = None


class BaseFormView(discord.ui.View):
    """Base class for owner-bound ephemeral configuration views."""

    def __init__(self, *, owner_id: int, timeout: float = 900) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.bound_message: discord.InteractionMessage | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Limit interactive controls to the user who opened the command flow."""
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            embed=build_result_embed(
                DiscordCommandResult(
                    title="Form Locked",
                    message="Only the user who opened this command form can interact with it.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            ),
            ephemeral=True,
        )
        return False

    async def finish(self, result: DiscordCommandResult) -> None:
        """Replace the original interaction response with the final command result."""
        if self.bound_message is not None:
            await self.bound_message.edit(embed=build_result_embed(result), view=None)

    async def finish_with_interaction(
        self,
        interaction: discord.Interaction,
        result: DiscordCommandResult,
    ) -> None:
        """Finish one form flow while preserving public success visibility."""
        embed = build_result_embed(result)
        if self.bound_message is None:
            if interaction.response.is_done():
                if result.ephemeral:
                    try:
                        await interaction.edit_original_response(embed=embed)
                    except discord.HTTPException:
                        pass
                elif interaction.channel is not None:
                    await interaction.channel.send(embed=_build_public_actor_embed(result, interaction.user.mention))
            else:
                if result.ephemeral:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.response.defer(ephemeral=True)
                    if interaction.channel is not None:
                        await interaction.channel.send(embed=_build_public_actor_embed(result, interaction.user.mention))
                    with suppress(discord.HTTPException):
                        await interaction.delete_original_response()
            return

        if result.ephemeral:
            if interaction.response.is_done():
                await self.bound_message.edit(embed=embed, view=None)
            else:
                await interaction.response.defer(ephemeral=True)
                await self.bound_message.edit(embed=embed, view=None)
            return

        with suppress(discord.HTTPException):
            await self.bound_message.edit(view=None)
        if interaction.response.is_done():
            if interaction.channel is not None:
                await interaction.channel.send(embed=_build_public_actor_embed(result, interaction.user.mention))
        else:
            await interaction.response.defer(ephemeral=True)
            if interaction.channel is not None:
                await interaction.channel.send(embed=_build_public_actor_embed(result, interaction.user.mention))
        with suppress(discord.HTTPException):
            await interaction.delete_original_response()
        with suppress(discord.HTTPException):
            await self.bound_message.delete()

    async def rerender(self) -> None:
        """Refresh the original interaction response with the current form state."""
        if self.bound_message is not None:
            await self.bound_message.edit(embed=self.render_embed(), view=self)

    def render_embed(self) -> discord.Embed:
        """Render the current form state into one Discord embed."""
        raise NotImplementedError
