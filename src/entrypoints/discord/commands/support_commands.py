"""Slash-command registration for support tickets."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.localization import Localizer

from ..helpers import (
    command_unavailable_result,
    defer_interaction_response,
    normalize_optional_text,
    send_initial_result,
    send_modal_response,
)
from ..ui.support_ui import SupportCreateModal, submit_support_ticket
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text


def register_support_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/support` for creating support tickets."""
    category_choices = [
        discord.app_commands.Choice(name=command_text(localizer, "support.choices.bug"), value="bug"),
        discord.app_commands.Choice(name=command_text(localizer, "support.choices.question"), value="question"),
        discord.app_commands.Choice(name=command_text(localizer, "support.choices.idea"), value="idea"),
        discord.app_commands.Choice(name=command_text(localizer, "support.choices.other"), value="other"),
    ]

    @tree.command(name="support", description=command_text(localizer, "support.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            category="support.options.category",
            title="support.options.title",
            description="support.options.description",
        )
    )
    @discord.app_commands.choices(category=category_choices)
    async def support(
        interaction: discord.Interaction,
        category: discord.app_commands.Choice[str] | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        language_hint = localizer.resolve_language(await ui_data_provider.get_thread_language(interaction.channel_id))
        normalized_title = normalize_optional_text(title)
        normalized_description = normalize_optional_text(description)
        if services.support.support_discord_channel_id is None:
            await send_initial_result(interaction, services.support.support_unavailable_result(language_hint=language_hint))
            return
        if category is None or normalized_title is None or normalized_description is None:
            await send_modal_response(
                interaction,
                SupportCreateModal(
                    services=services,
                    localizer=localizer,
                    language=language_hint,
                    default_category=None if category is None else category.value,
                    default_title=normalized_title,
                    default_description=normalized_description,
                ),
            )
            return

        await defer_interaction_response(interaction, ephemeral=True)
        await submit_support_ticket(
            interaction,
            services=services,
            localizer=localizer,
            category=category.value,
            title=normalized_title,
            description=normalized_description,
            language_hint=language_hint,
        )
