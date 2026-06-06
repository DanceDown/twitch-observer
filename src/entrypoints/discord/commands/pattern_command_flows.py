"""UI flow helpers for pattern command entrypoints."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..dispatch import dispatch_disable_pattern, dispatch_enable_pattern, dispatch_remove_pattern
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.patterns.home import PatternHomeView
from ..ui.patterns.id_actions import PatternActionSelectionModal, PatternIdActionView
from ..ui.patterns.selection import PatternEditSelectionModal, PatternPickerView
from ..ui.patterns.state import PatternActionKind, PatternEditorMode, PatternFormState
from ..ui.shared import start_form
from ..ui_data import DiscordUIDataProvider
from .pattern_command_state import resolve_pattern_identifier


async def open_ping_add_flow(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    initial_state: PatternFormState | None = None,
) -> None:
    language = await data_provider.get_thread_language(interaction.channel_id) or localizer.default_language
    await start_form(
        interaction,
        view=PatternHomeView(
            owner_id=interaction.user.id,
            language=localizer.resolve_language(language),
            services=services,
            data_provider=data_provider,
            discord_channel_id=interaction.channel_id,
            mode=PatternEditorMode.ADD,
            state=initial_state,
            localizer=localizer,
        ),
    )


async def open_ping_edit_flow(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    pattern_id: int | None,
    state_overrides: dict[str, object] | None,
) -> None:
    language = await data_provider.get_thread_language(interaction.channel_id) or localizer.default_language
    resolved_language = localizer.resolve_language(language)
    if pattern_id is not None:
        resolved_pattern_id = await resolve_pattern_identifier(data_provider, interaction.channel_id, pattern_id)
        pattern = await data_provider.get_pattern(interaction.channel_id, resolved_pattern_id)
        if pattern is None:
            await send_initial_result(
                interaction,
                build_result(
                    localizer,
                    "discord.pattern_ui.errors.not_found",
                    language=resolved_language,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await start_form(
            interaction,
            view=PatternHomeView(
                owner_id=interaction.user.id,
                language=resolved_language,
                services=services,
                data_provider=data_provider,
                discord_channel_id=interaction.channel_id,
                mode=PatternEditorMode.EDIT,
                state=PatternFormState(
                    pattern_id=pattern.pattern.pattern_id,
                    pattern_text=pattern.pattern.regex,
                    is_regex=pattern.pattern.is_regex,
                    channel_scope_mode=pattern.pattern.channel_scope_mode,
                    selected_channels=list(pattern.channel_logins),
                    selected_channel_names=list(pattern.channel_display_names),
                    user_scope_mode=pattern.pattern.user_scope_mode,
                    selected_users=list(pattern.user_logins),
                    selected_user_names=list(pattern.user_display_names),
                    sub_state=pattern.pattern.sub_state,
                    offline_state=pattern.pattern.offline_state,
                    case_sensitive=pattern.pattern.case_sensitive,
                    color=pattern.pattern.color,
                    priority=pattern.pattern.priority,
                ),
                localizer=localizer,
            ),
        )
        return

    view = PatternPickerView(
        owner_id=interaction.user.id,
        language=resolved_language,
        services=services,
        data_provider=data_provider,
        discord_channel_id=interaction.channel_id,
        state_overrides=state_overrides,
        localizer=localizer,
    )
    prepare_result = await view.prepare()
    if prepare_result is not None:
        await send_initial_result(interaction, prepare_result)
        return
    await interaction.response.send_modal(
        PatternEditSelectionModal(
            parent=view,
            patterns=view._patterns,
            localizer=localizer,
            language=resolved_language,
        )
    )


async def handle_ping_state_action(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    step: UIFlowStep,
    action: PatternActionKind,
    pattern_id: int | None,
) -> None:
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.PATTERN, step=step):
        return
    language = await ui_data_provider.get_thread_language(interaction.channel_id) or localizer.default_language
    resolved_language = localizer.resolve_language(language)
    if pattern_id is None:
        view = PatternIdActionView(
            owner_id=interaction.user.id,
            language=resolved_language,
            services=services,
            data_provider=ui_data_provider,
            discord_channel_id=interaction.channel_id,
            action=action,
            localizer=localizer,
        )
        prepare_result = await view.prepare()
        if prepare_result is not None:
            await send_initial_result(interaction, prepare_result)
            return
        await interaction.response.send_modal(
            PatternActionSelectionModal(
                title={
                    PatternActionKind.REMOVE: localizer.text("discord.pattern_ui.action.remove_title", language=resolved_language),
                    PatternActionKind.DISABLE: localizer.text("discord.pattern_ui.action.disable_title", language=resolved_language),
                    PatternActionKind.ENABLE: localizer.text("discord.pattern_ui.action.enable_title", language=resolved_language),
                }[action],
                parent=view,
                patterns=view._patterns,
                localizer=localizer,
                language=resolved_language,
            )
        )
        return

    resolved_pattern_id = await resolve_pattern_identifier(ui_data_provider, interaction.channel_id, pattern_id)
    if action is PatternActionKind.REMOVE:
        result = await dispatch_remove_pattern(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    elif action is PatternActionKind.DISABLE:
        result = await dispatch_disable_pattern(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    else:
        result = await dispatch_enable_pattern(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    await send_initial_result(interaction, result)
