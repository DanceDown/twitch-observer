"""Slash-command registration for permission management."""

from __future__ import annotations

from dataclasses import dataclass

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.utils.permissions import PERMISSION_CHOICES

from ..dispatch import dispatch_clear_permissions, dispatch_grant_permissions, dispatch_revoke_permissions
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result, split_csv_values
from ..ui.permission_ui import PermissionModal
from ..ui.shared import DiscordModalContext
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text


@dataclass(slots=True, frozen=True)
class _PermissionCommandContext:
    services: DiscordServiceBundle
    ui_data_provider: DiscordUIDataProvider
    localizer: Localizer
    valid_permissions: set[str]


def register_permission_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/permission` action subcommands."""
    group = discord.app_commands.Group(
        name="permission",
        description=command_text(localizer, "permission.description"),
    )
    valid_permissions = {value for value, _ in PERMISSION_CHOICES}
    context = _PermissionCommandContext(
        services=services,
        ui_data_provider=ui_data_provider,
        localizer=localizer,
        valid_permissions=valid_permissions,
    )

    @group.command(name="grant", description=command_text(localizer, "permission.grant.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            target_user="permission.grant.options.target_user",
            permissions="permission.grant.options.permissions",
        )
    )
    async def permission_grant(
        interaction: discord.Interaction,
        target_user: discord.User | None = None,
        permissions: str | None = None,
    ) -> None:
        await _handle_permission_grant(
            interaction,
            target_user=target_user,
            permissions=permissions,
            context=context,
        )

    @group.command(name="revoke", description=command_text(localizer, "permission.revoke.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            target_user="permission.revoke.options.target_user",
            permissions="permission.revoke.options.permissions",
        )
    )
    async def permission_revoke(
        interaction: discord.Interaction,
        target_user: discord.User | None = None,
        permissions: str | None = None,
    ) -> None:
        await _handle_permission_revoke(
            interaction,
            target_user=target_user,
            permissions=permissions,
            context=context,
        )

    @group.command(name="clear", description=command_text(localizer, "permission.clear.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, target_user="permission.clear.options.target_user"))
    async def permission_clear(interaction: discord.Interaction, target_user: discord.User | None = None) -> None:
        await _handle_permission_clear(
            interaction,
            target_user=target_user,
            context=context,
        )

    tree.add_command(group)


async def _handle_permission_grant(
    interaction: discord.Interaction,
    *,
    target_user: discord.User | None,
    permissions: str | None,
    context: _PermissionCommandContext,
) -> None:
    if not await _ensure_permission_command_context(interaction, context.services):
        return
    parsed_permissions = _parse_permissions(permissions, context.valid_permissions)
    if target_user is None or not parsed_permissions:
        await _open_permission_modal(
            interaction,
            context=context,
            action="grant",
            default_user_id=target_user.id if target_user is not None else None,
            default_permissions=parsed_permissions,
        )
        return
    result = await dispatch_grant_permissions(
        context.services,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        target_user_id=target_user.id,
        permissions=parsed_permissions,
    )
    await send_initial_result(interaction, result)


async def _handle_permission_revoke(
    interaction: discord.Interaction,
    *,
    target_user: discord.User | None,
    permissions: str | None,
    context: _PermissionCommandContext,
) -> None:
    if not await _ensure_permission_command_context(interaction, context.services):
        return
    parsed_permissions = _parse_permissions(permissions, context.valid_permissions)
    if target_user is None or not parsed_permissions:
        await _open_permission_modal(
            interaction,
            context=context,
            action="revoke",
            default_user_id=target_user.id if target_user is not None else None,
            default_permissions=parsed_permissions,
        )
        return
    result = await dispatch_revoke_permissions(
        context.services,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        target_user_id=target_user.id,
        permissions=parsed_permissions,
    )
    await send_initial_result(interaction, result)


async def _handle_permission_clear(
    interaction: discord.Interaction,
    *,
    target_user: discord.User | None,
    context: _PermissionCommandContext,
) -> None:
    if not await _ensure_permission_command_context(interaction, context.services):
        return
    if target_user is None:
        await _open_permission_modal(
            interaction,
            context=context,
            action="clear",
        )
        return
    result = await dispatch_clear_permissions(
        context.services,
        discord_channel_id=interaction.channel_id,
        requester_id=interaction.user.id,
        target_user_id=target_user.id,
    )
    await send_initial_result(interaction, result)


async def _ensure_permission_command_context(interaction: discord.Interaction, services: DiscordServiceBundle) -> bool:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return False
    return await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.PERMISSION, step=UIFlowStep.ROOT)


def _parse_permissions(permissions: str | None, valid_permissions: set[str]) -> tuple[str, ...]:
    return tuple(value.strip().lower() for value in split_csv_values(permissions) if value.strip().lower() in valid_permissions)


async def _open_permission_modal(
    interaction: discord.Interaction,
    *,
    context: _PermissionCommandContext,
    action: str,
    default_user_id: int | None = None,
    default_permissions: tuple[str, ...] = (),
) -> None:
    language = await context.ui_data_provider.get_thread_language(interaction.channel_id) or context.localizer.default_language
    await interaction.response.send_modal(
        PermissionModal(
            title=context.localizer.text(
                f"discord.permission_ui.modal.{action}.title",
                language=context.localizer.resolve_language(language),
            ),
            context=DiscordModalContext(
                services=context.services,
                discord_channel_id=interaction.channel_id,
                requester_id=interaction.user.id,
                localizer=context.localizer,
                language=context.localizer.resolve_language(language),
            ),
            action=action,
            default_user_id=default_user_id,
            default_permissions=default_permissions,
        )
    )
