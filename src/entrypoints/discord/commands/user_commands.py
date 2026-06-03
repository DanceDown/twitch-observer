"""Slash-command registration for tracked Twitch users."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle
from src.events.event_types import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..dispatch import dispatch_add_tracked_user, dispatch_remove_tracked_user
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.user_ui import UserNameModal, UserSelectionModal
from ..ui_data import DiscordUIDataProvider


def register_user_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/user` action subcommands."""

    group = discord.app_commands.Group(name="user", description="Add or remove tracked Twitch users.")

    @group.command(name="add", description="Add one tracked Twitch user.")
    @discord.app_commands.describe(twitch_user_login="Twitch user login.")
    async def user_add(interaction: discord.Interaction, twitch_user_login: str | None = None) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.USER, step=UIFlowStep.ROOT):
            return
        normalized_login = twitch_user_login.strip() if twitch_user_login is not None else ""
        if not normalized_login:
            language = await ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language
            await interaction.response.send_modal(
                UserNameModal(
                    services=services,
                    discord_channel_id=interaction.channel_id,
                    requester_id=interaction.user.id,
                    action="add",
                    localizer=localizer,
                    language=localizer.resolve_language(language),
                )
            )
            return
        result = await dispatch_add_tracked_user(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_user_login=normalized_login,
        )
        await send_initial_result(interaction, result)

    @group.command(name="remove", description="Remove one tracked Twitch user.")
    @discord.app_commands.describe(twitch_user_login="Tracked Twitch user login.")
    async def user_remove(interaction: discord.Interaction, twitch_user_login: str | None = None) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.USER, step=UIFlowStep.REMOVE):
            return
        normalized_login = twitch_user_login.strip() if twitch_user_login is not None else ""
        if not normalized_login:
            language = await ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language
            tracked_users = await ui_data_provider.list_tracked_users(interaction.channel_id)
            if not tracked_users:
                await send_initial_result(
                    interaction,
                    build_result(
                        localizer,
                        "discord.user_ui.errors.no_users",
                        language=localizer.resolve_language(language),
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )
                return
            await interaction.response.send_modal(
                UserSelectionModal(
                    services=services,
                    discord_channel_id=interaction.channel_id,
                    requester_id=interaction.user.id,
                    tracked_users=tracked_users,
                    localizer=localizer,
                    language=localizer.resolve_language(language),
                )
            )
            return
        result = await dispatch_remove_tracked_user(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            twitch_user_login=normalized_login,
        )
        await send_initial_result(interaction, result)

    tree.add_command(group)
