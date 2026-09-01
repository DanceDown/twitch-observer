"""Slash-command registration for support tickets."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import CreateSupportTicketCommand
from src.localization import Localizer

from ..dispatch import dispatch_create_support_ticket
from ..helpers import command_unavailable_result, defer_interaction_response, resolve_interaction_language, send_initial_result
from ..ui.support_ui import send_new_support_ticket
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text


def register_support_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/support` for creating support tickets."""
    _ = ui_data_provider
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
        category: discord.app_commands.Choice[str],
        title: str,
        description: str,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        await defer_interaction_response(interaction, ephemeral=True)
        language_hint = resolve_interaction_language(localizer, interaction)
        creation = await dispatch_create_support_ticket(
            services,
            CreateSupportTicketCommand(
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                category=category.value,
                title=title,
                description=description,
                language_hint=language_hint,
            ),
        )
        if creation.ticket is None:
            await send_initial_result(interaction, creation.result)
            return

        if not await send_new_support_ticket(
            client=interaction.client,
            creation=creation,
            services=services,
            localizer=localizer,
        ):
            await send_initial_result(interaction, services.support.support_channel_delivery_failed_result(creation.ticket))
            return

        await send_initial_result(interaction, creation.result)
