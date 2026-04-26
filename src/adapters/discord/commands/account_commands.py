from __future__ import annotations

"""Slash-command registration for Twitch account management."""

import discord

from src.events.event_bus import EventBus
from src.localization import Localizer

from ..ui.account_ui import AccountMenuView
from ..ui.shared import start_form
from ..ui_data import DiscordUIDataProvider


def register_account_commands(
    tree: discord.app_commands.CommandTree,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register the single-word `/account` command."""

    @tree.command(name="account", description="Connect or disconnect your Twitch account.")
    async def account(interaction: discord.Interaction) -> None:
        await start_form(
            interaction,
            view=AccountMenuView(
                owner_id=interaction.user.id,
                event_bus=event_bus,
                discord_channel_id=interaction.channel_id,
                data_provider=ui_data_provider,
                localizer=localizer,
            ),
        )
