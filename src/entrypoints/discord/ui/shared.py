"""Shared Discord UI primitives used across command-specific flows."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

import discord

from src.entrypoints.discord.helpers import build_public_result_embed
from src.discord_results import build_result
from src.events.event_types import DiscordCommandResult, DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import DEFAULT_LANGUAGE, Localizer
from src.utils.discord_embeds import build_result_embed

from ..dispatch import dispatch_ui_flow_decision

if TYPE_CHECKING:
    from ..ui_data import DiscordUIDataProvider

COLOR_PICKER_URL = "https://htmlcolorcodes.com/color-picker/"


def build_form_embed(result: DiscordCommandResult) -> discord.Embed:
    """Render one neutral configuration embed used by interactive command forms."""
    return build_result_embed(
        result
    )


async def start_form(
    interaction: discord.Interaction,
    *,
    view: BaseFormView,
) -> None:
    """Send the original ephemeral interaction response and bind the view message."""
    await interaction.response.send_message(embed=view.render_embed(), view=view, ephemeral=True)
    view.bound_message = await interaction.original_response()


def resolve_context_language(
    *,
    localizer: Localizer,
    data_provider: DiscordUIDataProvider | None = None,
    discord_channel_id: int | None = None,
) -> str:
    """Resolve the active UI language for one Discord context."""
    if data_provider is None or discord_channel_id is None:
        return localizer.default_language
    return localizer.resolve_language(data_provider.get_thread_language(discord_channel_id))


class BaseFormView(discord.ui.View):
    """Base class for owner-bound ephemeral configuration views."""

    def __init__(
        self,
        *,
        owner_id: int,
        localizer: Localizer,
        language: str = DEFAULT_LANGUAGE,
        timeout: float = 900,
    ) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self._localizer = localizer
        self._language = language
        self.bound_message: discord.InteractionMessage | None = None

    @property
    def language(self) -> str:
        """Return the resolved UI language for this form."""
        return self._language

    def text(self, key: str, **placeholders: object) -> str:
        """Resolve one localized UI string for this view."""
        return self._localizer.text(key, language=self._language, **placeholders)

    def result(
        self,
        key: str,
        *,
        style: DiscordResultStyle = DiscordResultStyle.INFO,
        ephemeral: bool = True,
        **placeholders: object,
    ) -> DiscordCommandResult:
        """Resolve one localized command result for this form."""
        return build_result(
            self._localizer,
            key,
            language=self._language,
            style=style,
            ephemeral=ephemeral,
            **placeholders,
        )

    def form_embed(self, result_key: str, **placeholders: object) -> discord.Embed:
        """Build one localized configuration embed for the current form state."""
        return build_form_embed(
            self.result(
                result_key,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                **placeholders,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Limit interactive controls to the user who opened the command flow."""
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            embed=build_result_embed(self.result("discord.shared.form_locked", style=DiscordResultStyle.ERROR, ephemeral=True)),
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
                    with suppress(discord.HTTPException):
                        await interaction.edit_original_response(embed=embed)
                elif interaction.channel is not None:
                    await interaction.channel.send(embed=build_public_result_embed(result))
            else:
                if result.ephemeral:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.response.defer(ephemeral=True)
                    if interaction.channel is not None:
                        await interaction.channel.send(embed=build_public_result_embed(result))
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
                await interaction.channel.send(embed=build_public_result_embed(result))
        else:
            await interaction.response.defer(ephemeral=True)
            if interaction.channel is not None:
                await interaction.channel.send(embed=build_public_result_embed(result))
        with suppress(discord.HTTPException):
            await interaction.delete_original_response()
        with suppress(discord.HTTPException):
            await self.bound_message.delete()

    async def ensure_step_allowed(
        self,
        interaction: discord.Interaction,
        services,
        *,
        flow: UIFlowKind,
        step: UIFlowStep,
        discord_channel_id: int | None,
    ) -> bool:
        """Ask services before opening the next UI step."""
        decision = await dispatch_ui_flow_decision(
            services,
            discord_channel_id=discord_channel_id,
            requester_id=interaction.user.id,
            flow=flow,
            step=step,
        )
        if decision.open_ui:
            return True
        if decision.result is not None:
            await self.finish_with_interaction(interaction, decision.result)
        return False

    async def rerender(self) -> None:
        """Refresh the original interaction response with the current form state."""
        if self.bound_message is not None:
            await self.bound_message.edit(embed=self.render_embed(), view=self)

    def render_embed(self) -> discord.Embed:
        """Render the current form state into one Discord embed."""
        raise NotImplementedError
