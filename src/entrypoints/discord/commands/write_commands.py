"""Slash-command registration for manual Twitch writing."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.shared import resolve_context_language
from ..ui.write_ui import WriteModal
from ..ui_data import DiscordUIDataProvider


def register_write_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    *,
    reply_candidate_max_age_minutes: int,
    reply_candidate_limit: int,
) -> None:
    """Register the single-word `/write` command."""

    @tree.command(name="write", description="Send a Twitch message from the linked account.")
    async def write(interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.WRITE, step=UIFlowStep.ROOT):
            return
        language = resolve_context_language(
            localizer=localizer,
            data_provider=ui_data_provider,
            discord_channel_id=interaction.channel_id,
        )
        tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
        if not tracked_channels:
            await send_initial_result(
                interaction,
                build_result(
                    localizer,
                    "discord.write_ui.errors.no_channels",
                    language=language,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        recent_replies = await ui_data_provider.list_recent_write_reply_candidates(
            discord_channel_id=interaction.channel_id,
            max_age_minutes=reply_candidate_max_age_minutes,
            limit=min(max(reply_candidate_limit, 1), 25),
        )
        await interaction.response.send_modal(
            WriteModal(
                services=services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                tracked_channels=tracked_channels,
                reply_candidates=recent_replies,
                localizer=localizer,
                language=language,
            )
        )
