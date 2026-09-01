"""Slash-command registration for ping management."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import AddPatternCommand, EditPatternCommand
from src.events.pattern_scopes import ChannelScopeMode, OfflineScope, SubscriptionScope, UserScopeMode
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_add_pattern, dispatch_edit_pattern
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, normalize_optional_text, send_initial_result, split_csv_values
from ..ui.patterns.state import PatternActionKind
from ..ui_data import DiscordUIDataProvider
from .localized import command_descriptions, command_text
from .pattern_command_flows import PatternFlowContext, handle_ping_state_action, open_ping_add_flow, open_ping_edit_flow
from .pattern_command_state import (
    PatternAddCommandOptions,
    PatternEditCommandOptions,
    build_pattern_add_state,
    build_pattern_edit_overrides,
    resolve_pattern_identifier,
    resolved_channel_scope_mode,
    resolved_user_scope_mode,
)


def register_pattern_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/ping` action subcommands."""
    group = discord.app_commands.Group(name="ping", description=command_text(localizer, "ping.description"))

    channel_scope_choices = [
        discord.app_commands.Choice(
            name=command_text(localizer, f"ping.choices.channel_scope.{scope.value}"),
            value=scope.value,
        )
        for scope in (
            ChannelScopeMode.ALL_TRACKED,
            ChannelScopeMode.ONLY_SELECTED,
            ChannelScopeMode.ALL_EXCEPT_SELECTED,
        )
    ]
    user_scope_choices = [
        discord.app_commands.Choice(
            name=command_text(localizer, f"ping.choices.user_scope.{scope.value}"),
            value=scope.value,
        )
        for scope in (
            UserScopeMode.ALL_USERS,
            UserScopeMode.ALL_TRACKED,
            UserScopeMode.ALL_TRACKED_EXCEPT_SELECTED,
            UserScopeMode.ONLY_SELECTED,
            UserScopeMode.ALL_EXCEPT_SELECTED,
        )
    ]
    sub_state_choices = [
        discord.app_commands.Choice(
            name=command_text(localizer, f"ping.choices.sub_state.{scope.value}"),
            value=scope.value,
        )
        for scope in (SubscriptionScope.ALL, SubscriptionScope.SUBS, SubscriptionScope.NON_SUBS)
    ]
    offline_state_choices = [
        discord.app_commands.Choice(
            name=command_text(localizer, f"ping.choices.offline_state.{scope.value}"),
            value=scope.value,
        )
        for scope in (OfflineScope.BOTH, OfflineScope.ONLINE, OfflineScope.OFFLINE)
    ]
    context = PatternFlowContext(services=services, data_provider=ui_data_provider, localizer=localizer)

    @group.command(name="add", description=command_text(localizer, "ping.add.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            pattern_text="ping.add.options.pattern_text",
            is_regex="ping.add.options.is_regex",
            channel_scope_mode="ping.add.options.channel_scope_mode",
            channel_logins="ping.add.options.channel_logins",
            user_scope_mode="ping.add.options.user_scope_mode",
            user_logins="ping.add.options.user_logins",
            sub_state="ping.add.options.sub_state",
            offline_state="ping.add.options.offline_state",
            case_sensitive="ping.add.options.case_sensitive",
            color="ping.add.options.color",
            priority="ping.add.options.priority",
            disabled="ping.add.options.disabled",
        )
    )
    @discord.app_commands.choices(
        channel_scope_mode=channel_scope_choices,
        user_scope_mode=user_scope_choices,
        sub_state=sub_state_choices,
        offline_state=offline_state_choices,
    )
    # discord.py derives slash-command options from the callback signature.
    async def ping_add(  # noqa: PLR0913
        interaction: discord.Interaction,
        *,
        pattern_text: str | None = None,
        is_regex: bool = False,
        channel_scope_mode: discord.app_commands.Choice[str] | None = None,
        channel_logins: str | None = None,
        user_scope_mode: discord.app_commands.Choice[str] | None = None,
        user_logins: str | None = None,
        sub_state: discord.app_commands.Choice[str] | None = None,
        offline_state: discord.app_commands.Choice[str] | None = None,
        case_sensitive: bool = False,
        color: str | None = None,
        priority: int | None = None,
        disabled: bool = False,
    ) -> None:
        await _handle_ping_add(
            interaction,
            options=PatternAddCommandOptions(
                pattern_text=pattern_text,
                is_regex=is_regex,
                channel_scope_mode=channel_scope_mode,
                channel_logins=channel_logins,
                user_scope_mode=user_scope_mode,
                user_logins=user_logins,
                sub_state=sub_state,
                offline_state=offline_state,
                case_sensitive=case_sensitive,
                color=color,
                priority=priority,
                disabled=disabled,
            ),
            context=context,
        )

    @group.command(name="edit", description=command_text(localizer, "ping.edit.description"))
    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            pattern_id="ping.edit.options.pattern_id",
            pattern_text="ping.edit.options.pattern_text",
            is_regex="ping.edit.options.is_regex",
            channel_scope_mode="ping.edit.options.channel_scope_mode",
            channel_logins="ping.edit.options.channel_logins",
            user_scope_mode="ping.edit.options.user_scope_mode",
            user_logins="ping.edit.options.user_logins",
            sub_state="ping.edit.options.sub_state",
            offline_state="ping.edit.options.offline_state",
            case_sensitive="ping.edit.options.case_sensitive",
            color="ping.edit.options.color",
            clear_color="ping.edit.options.clear_color",
            priority="ping.edit.options.priority",
        )
    )
    @discord.app_commands.choices(
        channel_scope_mode=channel_scope_choices,
        user_scope_mode=user_scope_choices,
        sub_state=sub_state_choices,
        offline_state=offline_state_choices,
    )
    # discord.py derives slash-command options from the callback signature.
    async def ping_edit(  # noqa: PLR0913
        interaction: discord.Interaction,
        *,
        pattern_id: int | None = None,
        pattern_text: str | None = None,
        is_regex: bool | None = None,
        channel_scope_mode: discord.app_commands.Choice[str] | None = None,
        channel_logins: str | None = None,
        user_scope_mode: discord.app_commands.Choice[str] | None = None,
        user_logins: str | None = None,
        sub_state: discord.app_commands.Choice[str] | None = None,
        offline_state: discord.app_commands.Choice[str] | None = None,
        case_sensitive: bool | None = None,
        color: str | None = None,
        clear_color: bool = False,
        priority: int | None = None,
    ) -> None:
        await _handle_ping_edit(
            interaction,
            options=PatternEditCommandOptions(
                pattern_id=pattern_id,
                pattern_text=pattern_text,
                is_regex=is_regex,
                channel_scope_mode=channel_scope_mode,
                channel_logins=channel_logins,
                user_scope_mode=user_scope_mode,
                user_logins=user_logins,
                sub_state=sub_state,
                offline_state=offline_state,
                case_sensitive=case_sensitive,
                color=color,
                clear_color=clear_color,
                priority=priority,
            ),
            context=context,
        )

    @group.command(name="remove", description=command_text(localizer, "ping.remove.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, pattern_id="ping.remove.options.pattern_id"))
    async def ping_remove(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_ping_state_action(
            interaction,
            context=context,
            step=UIFlowStep.REMOVE,
            action=PatternActionKind.REMOVE,
            pattern_id=pattern_id,
        )

    @group.command(name="disable", description=command_text(localizer, "ping.disable.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, pattern_id="ping.disable.options.pattern_id"))
    async def ping_disable(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_ping_state_action(
            interaction,
            context=context,
            step=UIFlowStep.DISABLE,
            action=PatternActionKind.DISABLE,
            pattern_id=pattern_id,
        )

    @group.command(name="enable", description=command_text(localizer, "ping.enable.description"))
    @discord.app_commands.describe(**command_descriptions(localizer, pattern_id="ping.enable.options.pattern_id"))
    async def ping_enable(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await handle_ping_state_action(
            interaction,
            context=context,
            step=UIFlowStep.ENABLE,
            action=PatternActionKind.ENABLE,
            pattern_id=pattern_id,
        )

    tree.add_command(group)


async def _handle_ping_add(
    interaction: discord.Interaction,
    *,
    options: PatternAddCommandOptions,
    context: PatternFlowContext,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.PATTERN, step=UIFlowStep.ADD_PATTERN):
        return
    normalized_pattern_text = normalize_optional_text(options.pattern_text)
    if normalized_pattern_text is None:
        await open_ping_add_flow(
            interaction,
            context=context,
            initial_state=build_pattern_add_state(
                options,
                normalized_pattern_text=normalized_pattern_text,
            ),
        )
        return
    result = await dispatch_add_pattern(
        context.services,
        AddPatternCommand(
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_text=normalized_pattern_text,
            is_regex=options.is_regex,
            channel_scope_mode=resolved_channel_scope_mode(options.channel_scope_mode, options.channel_logins),
            twitch_channel_logins=split_csv_values(options.channel_logins),
            user_scope_mode=resolved_user_scope_mode(options.user_scope_mode, options.user_logins),
            twitch_user_logins=split_csv_values(options.user_logins),
            sub_state=SubscriptionScope(options.sub_state.value if options.sub_state is not None else SubscriptionScope.ALL.value),
            offline_state=OfflineScope(options.offline_state.value if options.offline_state is not None else OfflineScope.BOTH.value),
            case_sensitive=options.case_sensitive,
            color=normalize_optional_text(options.color),
            disabled=options.disabled,
            priority=options.priority,
        ),
    )
    await send_initial_result(interaction, result)


async def _handle_ping_edit(
    interaction: discord.Interaction,
    *,
    options: PatternEditCommandOptions,
    context: PatternFlowContext,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.PATTERN, step=UIFlowStep.ROOT):
        return
    normalized_pattern_text = normalize_optional_text(options.pattern_text)
    normalized_color = normalize_optional_text(options.color)
    if options.pattern_id is None or not _has_ping_edit_changes(
        options,
        normalized_pattern_text=normalized_pattern_text,
    ):
        await open_ping_edit_flow(
            interaction,
            context=context,
            pattern_id=options.pattern_id,
            state_overrides=build_pattern_edit_overrides(
                options,
                normalized_pattern_text=normalized_pattern_text,
                normalized_color=normalized_color,
            ),
        )
        return
    resolved_pattern_id = await resolve_pattern_identifier(context.data_provider, interaction.channel_id, options.pattern_id)
    result = await dispatch_edit_pattern(
        context.services,
        EditPatternCommand(
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
            pattern_text=normalized_pattern_text if options.pattern_text is not None else None,
            is_regex=options.is_regex,
            channel_scope_mode=_resolved_edit_channel_scope(options),
            twitch_channel_logins=split_csv_values(options.channel_logins) if options.channel_logins is not None else None,
            user_scope_mode=_resolved_edit_user_scope(options),
            twitch_user_logins=split_csv_values(options.user_logins) if options.user_logins is not None else None,
            sub_state=SubscriptionScope(options.sub_state.value) if options.sub_state is not None else None,
            offline_state=OfflineScope(options.offline_state.value) if options.offline_state is not None else None,
            case_sensitive=options.case_sensitive,
            color=normalized_color,
            clear_color=options.clear_color,
            priority=options.priority,
        ),
    )
    await send_initial_result(interaction, result)


def _has_ping_edit_changes(
    options: PatternEditCommandOptions,
    *,
    normalized_pattern_text: str | None,
) -> bool:
    return any(
        (
            normalized_pattern_text is not None,
            options.is_regex is not None,
            options.channel_scope_mode is not None,
            options.channel_logins is not None,
            options.user_scope_mode is not None,
            options.user_logins is not None,
            options.sub_state is not None,
            options.offline_state is not None,
            options.case_sensitive is not None,
            options.color is not None,
            options.clear_color,
            options.priority is not None,
        )
    )


def _resolved_edit_channel_scope(options: PatternEditCommandOptions) -> ChannelScopeMode | None:
    if options.channel_scope_mode is not None:
        return ChannelScopeMode(options.channel_scope_mode.value)
    if split_csv_values(options.channel_logins):
        return ChannelScopeMode.ONLY_SELECTED
    return None


def _resolved_edit_user_scope(options: PatternEditCommandOptions) -> UserScopeMode | None:
    if options.user_scope_mode is not None:
        return UserScopeMode(options.user_scope_mode.value)
    if split_csv_values(options.user_logins):
        return UserScopeMode.ONLY_SELECTED
    return None
