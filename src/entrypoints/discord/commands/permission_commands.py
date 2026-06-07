"""Slash-command registration for permission management."""

from __future__ import annotations

import discord

from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.utils.permissions import PERMISSION_CHOICES

from ..dispatch import dispatch_clear_permissions, dispatch_grant_permissions, dispatch_revoke_permissions
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result, split_csv_values
from ..ui.permission_ui import PermissionModal
from ..ui_data import DiscordUIDataProvider


def register_permission_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/permission` action subcommands."""

    group = discord.app_commands.Group(
        name="permission",
        description="Grant, revoke, or clear the permissions of a Discord user.",
    )
    valid_permissions = {value for value, _ in PERMISSION_CHOICES}

    @group.command(name="grant", description="Grant permissions to one Discord user.")
    @discord.app_commands.describe(
        target_user="Discord user to update.",
        permissions="Comma-separated permission values.",
    )
    async def permission_grant(
        interaction: discord.Interaction,
        target_user: discord.User | None = None,
        permissions: str | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.PERMISSION, step=UIFlowStep.ROOT):
            return
        if target_user is None or permissions is None or not permissions.strip():
            await _open_permission_modal(
                interaction,
                services=services,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
                action="grant",
                default_user_id=target_user.id if target_user is not None else None,
                default_permissions=tuple(
                    value.strip().lower() for value in split_csv_values(permissions) if value.strip().lower() in valid_permissions
                ),
            )
            return
        parsed_permissions = tuple(
            value.strip().lower() for value in split_csv_values(permissions) if value.strip().lower() in valid_permissions
        )
        result = await dispatch_grant_permissions(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            target_user_id=target_user.id,
            permissions=parsed_permissions,
        )
        await send_initial_result(interaction, result)

    @group.command(name="revoke", description="Revoke permissions from one Discord user.")
    @discord.app_commands.describe(
        target_user="Discord user to update.",
        permissions="Comma-separated permission values.",
    )
    async def permission_revoke(
        interaction: discord.Interaction,
        target_user: discord.User | None = None,
        permissions: str | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.PERMISSION, step=UIFlowStep.ROOT):
            return
        if target_user is None or permissions is None or not permissions.strip():
            await _open_permission_modal(
                interaction,
                services=services,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
                action="revoke",
                default_user_id=target_user.id if target_user is not None else None,
                default_permissions=tuple(
                    value.strip().lower() for value in split_csv_values(permissions) if value.strip().lower() in valid_permissions
                ),
            )
            return
        parsed_permissions = tuple(
            value.strip().lower() for value in split_csv_values(permissions) if value.strip().lower() in valid_permissions
        )
        result = await dispatch_revoke_permissions(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            target_user_id=target_user.id,
            permissions=parsed_permissions,
        )
        await send_initial_result(interaction, result)

    @group.command(name="clear", description="Clear all explicit permissions for one Discord user.")
    @discord.app_commands.describe(target_user="Discord user to update.")
    async def permission_clear(interaction: discord.Interaction, target_user: discord.User | None = None) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.PERMISSION, step=UIFlowStep.ROOT):
            return
        if target_user is None:
            await _open_permission_modal(
                interaction,
                services=services,
                ui_data_provider=ui_data_provider,
                localizer=localizer,
                action="clear",
            )
            return
        result = await dispatch_clear_permissions(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            target_user_id=target_user.id,
        )
        await send_initial_result(interaction, result)

    tree.add_command(group)


async def _open_permission_modal(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    action: str,
    default_user_id: int | None = None,
    default_permissions: tuple[str, ...] = (),
) -> None:
    language = await ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language
    await interaction.response.send_modal(
        PermissionModal(
            title=localizer.text(
                f"discord.permission_ui.modal.{action}.title",
                language=localizer.resolve_language(language),
            ),
            services=services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action=action,
            localizer=localizer,
            language=localizer.resolve_language(language),
            default_user_id=default_user_id,
            default_permissions=default_permissions,
        )
    )
