"""UI flow helpers for pattern command entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

import discord

from src.discord_results import build_result
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.discord_results import DiscordResultStyle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer

from ..dispatch import dispatch_disable_pattern, dispatch_enable_pattern, dispatch_remove_pattern
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.patterns.context import PatternViewContext
from ..ui.patterns.home import PatternHomeView
from ..ui.patterns.id_actions import PatternActionSelectionModal, PatternIdActionView
from ..ui.patterns.selection import PatternEditSelectionModal, PatternPickerView
from ..ui.patterns.state import PatternActionKind, PatternEditorMode, PatternFormState
from ..ui.shared import start_form
from ..ui_data import DiscordUIDataProvider
from .pattern_command_state import resolve_pattern_identifier


@dataclass(slots=True, frozen=True)
class PatternFlowContext:
    """Shared dependencies for pattern command UI/direct-action flows."""

    services: DiscordServiceBundle
    data_provider: DiscordUIDataProvider
    localizer: Localizer


async def open_ping_add_flow(
    interaction: discord.Interaction,
    *,
    context: PatternFlowContext,
    initial_state: PatternFormState | None = None,
) -> None:
    """Open the guided ping creation form."""
    language = await context.data_provider.get_thread_language(interaction.channel_id) or context.localizer.default_language
    await start_form(
        interaction,
        view=PatternHomeView(
            context=PatternViewContext(
                owner_id=interaction.user.id,
                language=context.localizer.resolve_language(language),
                services=context.services,
                data_provider=context.data_provider,
                discord_channel_id=interaction.channel_id,
                localizer=context.localizer,
            ),
            mode=PatternEditorMode.ADD,
            state=initial_state,
        ),
    )


async def open_ping_edit_flow(
    interaction: discord.Interaction,
    *,
    context: PatternFlowContext,
    pattern_id: int | None,
    state_overrides: dict[str, object] | None,
) -> None:
    """Open a guided ping edit form or pattern picker."""
    language = await context.data_provider.get_thread_language(interaction.channel_id) or context.localizer.default_language
    resolved_language = context.localizer.resolve_language(language)
    if pattern_id is not None:
        resolved_pattern_id = await resolve_pattern_identifier(context.data_provider, interaction.channel_id, pattern_id)
        pattern = await context.data_provider.get_pattern(interaction.channel_id, resolved_pattern_id)
        if pattern is None:
            await send_initial_result(
                interaction,
                build_result(
                    context.localizer,
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
                context=PatternViewContext(
                    owner_id=interaction.user.id,
                    language=resolved_language,
                    services=context.services,
                    data_provider=context.data_provider,
                    discord_channel_id=interaction.channel_id,
                    localizer=context.localizer,
                ),
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
            ),
        )
        return

    view = PatternPickerView(
        context=PatternViewContext(
            owner_id=interaction.user.id,
            language=resolved_language,
            services=context.services,
            data_provider=context.data_provider,
            discord_channel_id=interaction.channel_id,
            localizer=context.localizer,
        ),
        state_overrides=state_overrides,
    )
    prepare_result = await view.prepare()
    if prepare_result is not None:
        await send_initial_result(interaction, prepare_result)
        return
    await interaction.response.send_modal(
        PatternEditSelectionModal(
            parent=view,
            patterns=view._patterns,
            localizer=context.localizer,
            language=resolved_language,
        )
    )


async def handle_ping_state_action(
    interaction: discord.Interaction,
    *,
    context: PatternFlowContext,
    step: UIFlowStep,
    action: PatternActionKind,
    pattern_id: int | None,
) -> None:
    """Run a direct or modal-driven ping remove/enable/disable action."""
    if interaction.channel_id is None:
        await send_initial_result(interaction, command_unavailable_result())
        return
    if not await ensure_ui_flow_allowed(interaction, context.services, flow=UIFlowKind.PATTERN, step=step):
        return
    language = await context.data_provider.get_thread_language(interaction.channel_id) or context.localizer.default_language
    resolved_language = context.localizer.resolve_language(language)
    if pattern_id is None:
        view = PatternIdActionView(
            context=PatternViewContext(
                owner_id=interaction.user.id,
                language=resolved_language,
                services=context.services,
                data_provider=context.data_provider,
                discord_channel_id=interaction.channel_id,
                localizer=context.localizer,
            ),
            action=action,
        )
        prepare_result = await view.prepare()
        if prepare_result is not None:
            await send_initial_result(interaction, prepare_result)
            return
        await interaction.response.send_modal(
            PatternActionSelectionModal(
                title={
                    PatternActionKind.REMOVE: context.localizer.text(
                        "discord.pattern_ui.action.remove_title",
                        language=resolved_language,
                    ),
                    PatternActionKind.DISABLE: context.localizer.text(
                        "discord.pattern_ui.action.disable_title",
                        language=resolved_language,
                    ),
                    PatternActionKind.ENABLE: context.localizer.text(
                        "discord.pattern_ui.action.enable_title",
                        language=resolved_language,
                    ),
                }[action],
                parent=view,
                patterns=view._patterns,
                localizer=context.localizer,
                language=resolved_language,
            )
        )
        return

    resolved_pattern_id = await resolve_pattern_identifier(context.data_provider, interaction.channel_id, pattern_id)
    if action is PatternActionKind.REMOVE:
        result = await dispatch_remove_pattern(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    elif action is PatternActionKind.DISABLE:
        result = await dispatch_disable_pattern(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    else:
        result = await dispatch_enable_pattern(
            context.services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
        )
    await send_initial_result(interaction, result)
