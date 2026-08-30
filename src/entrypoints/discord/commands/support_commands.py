"""Slash-command registration for support tickets."""

from __future__ import annotations

from typing import cast

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.localization import Localizer
from src.services.support_command_service import SupportTicketCreateResult

from ..dispatch import dispatch_create_support_ticket
from ..helpers import command_unavailable_result, defer_interaction_response, resolve_interaction_language, send_initial_result
from ..ui.support_ui import send_new_support_ticket
from ..ui_data import DiscordUIDataProvider


def register_support_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/support` for creating support tickets."""
    _ = ui_data_provider
    category_choices = [
        discord.app_commands.Choice(name="Bug", value="bug"),
        discord.app_commands.Choice(name="Question", value="question"),
        discord.app_commands.Choice(name="Idea", value="idea"),
        discord.app_commands.Choice(name="Other", value="other"),
    ]

    @tree.command(name="support", description="Create a support ticket.")
    @discord.app_commands.describe(
        category="Support category.",
        title="Short title for the support request.",
        description="What happened or what do you need help with?",
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
        creation = cast(
            SupportTicketCreateResult,
            await dispatch_create_support_ticket(
                services,
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
