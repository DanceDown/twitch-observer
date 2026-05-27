"""Slash-command registration for ping management."""

from __future__ import annotations

import discord

from src.discord_results import build_result
from src.events.event_types import (
    ChannelScopeMode,
    DiscordResultStyle,
    OfflineScope,
    SubscriptionScope,
    UIFlowKind,
    UIFlowStep,
    UserScopeMode,
)
from src.localization import Localizer
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from ..dispatch import (
    dispatch_add_pattern,
    dispatch_disable_pattern,
    dispatch_edit_pattern,
    dispatch_enable_pattern,
    dispatch_remove_pattern,
)
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, normalize_optional_text, send_initial_result
from ..helpers import split_csv_values
from ..ui.patterns.home import PatternHomeView
from ..ui.patterns.id_actions import PatternActionSelectionModal, PatternIdActionView
from ..ui.patterns.selection import PatternEditSelectionModal, PatternPickerView
from ..ui.patterns.state import PatternActionKind, PatternEditorMode, PatternFormState
from ..ui.shared import start_form
from ..ui_data import DiscordUIDataProvider


def register_pattern_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Register `/ping` action subcommands."""

    group = discord.app_commands.Group(name="ping", description="Create, edit, remove, or disable/enable pings.")

    channel_scope_choices = [
        discord.app_commands.Choice(name="all_tracked", value="all_tracked"),
        discord.app_commands.Choice(name="only_selected", value="only_selected"),
        discord.app_commands.Choice(name="all_except_selected", value="all_except_selected"),
    ]
    user_scope_choices = [
        discord.app_commands.Choice(name="all_users", value="all_users"),
        discord.app_commands.Choice(name="all_tracked", value="all_tracked"),
        discord.app_commands.Choice(name="all_tracked_except_selected", value="all_tracked_except_selected"),
        discord.app_commands.Choice(name="only_selected", value="only_selected"),
        discord.app_commands.Choice(name="all_except_selected", value="all_except_selected"),
    ]
    sub_state_choices = [
        discord.app_commands.Choice(name="all", value="all"),
        discord.app_commands.Choice(name="subs", value="subs"),
        discord.app_commands.Choice(name="non_subs", value="non_subs"),
    ]
    offline_state_choices = [
        discord.app_commands.Choice(name="both", value="both"),
        discord.app_commands.Choice(name="online", value="online"),
        discord.app_commands.Choice(name="offline", value="offline"),
    ]

    @group.command(name="add", description="Add one ping or regex.")
    @discord.app_commands.describe(
        pattern_text="Pattern text.",
        is_regex="Use regex mode.",
        channel_scope_mode="Channel scope.",
        channel_logins="Comma-separated Twitch channel logins.",
        user_scope_mode="User scope.",
        user_logins="Comma-separated Twitch user logins.",
        sub_state="Subscriber filter.",
        offline_state="Live/offline filter.",
        case_sensitive="Case-sensitive matching.",
        color="Hex color.",
        priority="Priority 0-9.",
        disabled="Create as disabled.",
    )
    @discord.app_commands.choices(
        channel_scope_mode=channel_scope_choices,
        user_scope_mode=user_scope_choices,
        sub_state=sub_state_choices,
        offline_state=offline_state_choices,
    )
    async def ping_add(
        interaction: discord.Interaction,
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
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.PATTERN, step=UIFlowStep.ADD_PATTERN):
            return
        normalized_pattern_text = normalize_optional_text(pattern_text)
        if normalized_pattern_text is None:
            await _open_ping_add_flow(
                interaction,
                services=services,
                data_provider=ui_data_provider,
                localizer=localizer,
                initial_state=_build_pattern_add_state(
                    pattern_text=normalized_pattern_text,
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
                ),
            )
            return
        result = await dispatch_add_pattern(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_text=normalized_pattern_text,
            is_regex=is_regex,
            channel_scope_mode=_resolved_channel_scope_mode(channel_scope_mode, channel_logins),
            twitch_channel_logins=split_csv_values(channel_logins),
            user_scope_mode=_resolved_user_scope_mode(user_scope_mode, user_logins),
            twitch_user_logins=split_csv_values(user_logins),
            sub_state=SubscriptionScope(sub_state.value if sub_state is not None else SubscriptionScope.ALL.value),
            offline_state=OfflineScope(offline_state.value if offline_state is not None else OfflineScope.BOTH.value),
            case_sensitive=case_sensitive,
            color=normalize_optional_text(color),
            disabled=disabled,
            priority=priority,
        )
        await send_initial_result(interaction, result)

    @group.command(name="edit", description="Edit one existing ping or regex.")
    @discord.app_commands.describe(
        pattern_id="Pattern ID or display index.",
        pattern_text="New pattern text.",
        is_regex="New regex mode.",
        channel_scope_mode="New channel scope.",
        channel_logins="New comma-separated channel logins.",
        user_scope_mode="New user scope.",
        user_logins="New comma-separated user logins.",
        sub_state="New subscriber filter.",
        offline_state="New live/offline filter.",
        case_sensitive="New case-sensitive setting.",
        color="New hex color.",
        clear_color="Clear existing color.",
        priority="New priority 0-9.",
    )
    @discord.app_commands.choices(
        channel_scope_mode=channel_scope_choices,
        user_scope_mode=user_scope_choices,
        sub_state=sub_state_choices,
        offline_state=offline_state_choices,
    )
    async def ping_edit(
        interaction: discord.Interaction,
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
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.PATTERN, step=UIFlowStep.ROOT):
            return
        has_changes = any(
            (
                normalize_optional_text(pattern_text) is not None,
                is_regex is not None,
                channel_scope_mode is not None,
                channel_logins is not None,
                user_scope_mode is not None,
                user_logins is not None,
                sub_state is not None,
                offline_state is not None,
                case_sensitive is not None,
                color is not None,
                clear_color,
                priority is not None,
            )
        )
        if pattern_id is None or not has_changes:
            await _open_ping_edit_flow(
                interaction,
                services=services,
                data_provider=ui_data_provider,
                localizer=localizer,
                pattern_id=pattern_id,
                state_overrides=_build_pattern_edit_overrides(
                    pattern_text=normalize_optional_text(pattern_text),
                    is_regex=is_regex,
                    channel_scope_mode=channel_scope_mode,
                    channel_logins=channel_logins,
                    user_scope_mode=user_scope_mode,
                    user_logins=user_logins,
                    sub_state=sub_state,
                    offline_state=offline_state,
                    case_sensitive=case_sensitive,
                    color=normalize_optional_text(color),
                    clear_color=clear_color,
                    priority=priority,
                ),
            )
            return
        resolved_pattern_id = await _resolve_pattern_identifier(ui_data_provider, interaction.channel_id, pattern_id)
        result = await dispatch_edit_pattern(
            services,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=resolved_pattern_id,
            pattern_text=normalize_optional_text(pattern_text) if pattern_text is not None else None,
            is_regex=is_regex,
            channel_scope_mode=(
                ChannelScopeMode(channel_scope_mode.value)
                if channel_scope_mode is not None
                else ChannelScopeMode.ONLY_SELECTED
                if split_csv_values(channel_logins)
                else None
            ),
            twitch_channel_logins=split_csv_values(channel_logins) if channel_logins is not None else None,
            user_scope_mode=(
                UserScopeMode(user_scope_mode.value)
                if user_scope_mode is not None
                else UserScopeMode.ONLY_SELECTED
                if split_csv_values(user_logins)
                else None
            ),
            twitch_user_logins=split_csv_values(user_logins) if user_logins is not None else None,
            sub_state=SubscriptionScope(sub_state.value) if sub_state is not None else None,
            offline_state=OfflineScope(offline_state.value) if offline_state is not None else None,
            case_sensitive=case_sensitive,
            color=normalize_optional_text(color),
            clear_color=clear_color,
            priority=priority,
        )
        await send_initial_result(interaction, result)

    @group.command(name="remove", description="Remove one ping or regex.")
    @discord.app_commands.describe(pattern_id="Pattern ID or display index.")
    async def ping_remove(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await _handle_ping_state_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.REMOVE,
            action=PatternActionKind.REMOVE,
            pattern_id=pattern_id,
        )

    @group.command(name="disable", description="Disable one ping or regex.")
    @discord.app_commands.describe(pattern_id="Pattern ID or display index.")
    async def ping_disable(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await _handle_ping_state_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.DISABLE,
            action=PatternActionKind.DISABLE,
            pattern_id=pattern_id,
        )

    @group.command(name="enable", description="Enable one ping or regex.")
    @discord.app_commands.describe(pattern_id="Pattern ID or display index.")
    async def ping_enable(interaction: discord.Interaction, pattern_id: int | None = None) -> None:
        await _handle_ping_state_action(
            interaction,
            services=services,
            ui_data_provider=ui_data_provider,
            localizer=localizer,
            step=UIFlowStep.ENABLE,
            action=PatternActionKind.ENABLE,
            pattern_id=pattern_id,
        )

    tree.add_command(group)


async def _open_ping_add_flow(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    initial_state: PatternFormState | None = None,
) -> None:
    await start_form(
        interaction,
        view=PatternHomeView(
            owner_id=interaction.user.id,
            services=services,
            data_provider=data_provider,
            discord_channel_id=interaction.channel_id,
            mode=PatternEditorMode.ADD,
            state=initial_state,
            localizer=localizer,
        ),
    )


async def _open_ping_edit_flow(
    interaction: discord.Interaction,
    *,
    services: DiscordServiceBundle,
    data_provider: DiscordUIDataProvider,
    localizer: Localizer,
    pattern_id: int | None,
    state_overrides: dict[str, object] | None,
) -> None:
    if pattern_id is not None:
        resolved_pattern_id = await _resolve_pattern_identifier(data_provider, interaction.channel_id, pattern_id)
        pattern = await data_provider.get_pattern(interaction.channel_id, resolved_pattern_id)
        if pattern is None:
            await send_initial_result(
                interaction,
                build_result(
                    localizer,
                    "discord.pattern_ui.errors.not_found",
                    language=localizer.resolve_language(data_provider.get_thread_language(interaction.channel_id)),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await start_form(
            interaction,
            view=PatternHomeView(
                owner_id=interaction.user.id,
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
            language=localizer.resolve_language(data_provider.get_thread_language(interaction.channel_id)),
        )
    )


async def _handle_ping_state_action(
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
    if pattern_id is None:
        view = PatternIdActionView(
            owner_id=interaction.user.id,
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
                    PatternActionKind.REMOVE: localizer.text(
                        "discord.pattern_ui.action.remove_title",
                        language=localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id)),
                    ),
                    PatternActionKind.DISABLE: localizer.text(
                        "discord.pattern_ui.action.disable_title",
                        language=localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id)),
                    ),
                    PatternActionKind.ENABLE: localizer.text(
                        "discord.pattern_ui.action.enable_title",
                        language=localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id)),
                    ),
                }[action],
                parent=view,
                patterns=view._patterns,
                localizer=localizer,
                language=localizer.resolve_language(ui_data_provider.get_thread_language(interaction.channel_id)),
            )
        )
        return
    resolved_pattern_id = await _resolve_pattern_identifier(ui_data_provider, interaction.channel_id, pattern_id)
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


async def _resolve_pattern_identifier(
    ui_data_provider: DiscordUIDataProvider,
    discord_channel_id: int,
    pattern_id: int,
) -> int:
    patterns = await ui_data_provider.list_patterns(discord_channel_id)
    for item in patterns:
        if item.pattern.pattern_id == pattern_id:
            return item.pattern.pattern_id
    for item in patterns:
        if item.display_index == pattern_id:
            return item.pattern.pattern_id
    return pattern_id


def _build_pattern_add_state(
    *,
    pattern_text: str | None,
    is_regex: bool,
    channel_scope_mode: discord.app_commands.Choice[str] | None,
    channel_logins: str | None,
    user_scope_mode: discord.app_commands.Choice[str] | None,
    user_logins: str | None,
    sub_state: discord.app_commands.Choice[str] | None,
    offline_state: discord.app_commands.Choice[str] | None,
    case_sensitive: bool,
    color: str | None,
    priority: int | None,
) -> PatternFormState:
    return PatternFormState(
        pattern_text=pattern_text,
        is_regex=is_regex,
        channel_scope_mode=_resolved_channel_scope_mode(channel_scope_mode, channel_logins).value,
        selected_channels=list(split_csv_values(channel_logins)),
        selected_channel_names=list(split_csv_values(channel_logins)),
        user_scope_mode=_resolved_user_scope_mode(user_scope_mode, user_logins).value,
        selected_users=list(split_csv_values(user_logins)),
        selected_user_names=list(split_csv_values(user_logins)),
        sub_state=sub_state.value if sub_state is not None else SubscriptionScope.ALL.value,
        offline_state=offline_state.value if offline_state is not None else OfflineScope.BOTH.value,
        case_sensitive=case_sensitive,
        color=normalize_optional_text(color),
        priority=priority,
    )


def _build_pattern_edit_overrides(
    *,
    pattern_text: str | None,
    is_regex: bool | None,
    channel_scope_mode: discord.app_commands.Choice[str] | None,
    channel_logins: str | None,
    user_scope_mode: discord.app_commands.Choice[str] | None,
    user_logins: str | None,
    sub_state: discord.app_commands.Choice[str] | None,
    offline_state: discord.app_commands.Choice[str] | None,
    case_sensitive: bool | None,
    color: str | None,
    clear_color: bool,
    priority: int | None,
) -> dict[str, object]:
    overrides: dict[str, object] = {}
    if pattern_text is not None:
        overrides["pattern_text"] = pattern_text
    if is_regex is not None:
        overrides["is_regex"] = is_regex
    if channel_scope_mode is not None:
        overrides["channel_scope_mode"] = channel_scope_mode.value
        if channel_logins is not None:
            selected_channels = list(split_csv_values(channel_logins))
            overrides["selected_channels"] = selected_channels
            overrides["selected_channel_names"] = list(selected_channels)
    elif channel_logins is not None:
        selected_channels = list(split_csv_values(channel_logins))
        overrides["channel_scope_mode"] = ChannelScopeMode.ONLY_SELECTED.value
        overrides["selected_channels"] = selected_channels
        overrides["selected_channel_names"] = list(selected_channels)
    if user_scope_mode is not None:
        overrides["user_scope_mode"] = user_scope_mode.value
        if user_logins is not None:
            selected_users = list(split_csv_values(user_logins))
            overrides["selected_users"] = selected_users
            overrides["selected_user_names"] = list(selected_users)
    elif user_logins is not None:
        selected_users = list(split_csv_values(user_logins))
        overrides["user_scope_mode"] = UserScopeMode.ONLY_SELECTED.value
        overrides["selected_users"] = selected_users
        overrides["selected_user_names"] = list(selected_users)
    if sub_state is not None:
        overrides["sub_state"] = sub_state.value
    if offline_state is not None:
        overrides["offline_state"] = offline_state.value
    if case_sensitive is not None:
        overrides["case_sensitive"] = case_sensitive
    if clear_color:
        overrides["color"] = None
    elif color is not None:
        overrides["color"] = color
    if priority is not None:
        overrides["priority"] = priority
    return overrides


def _resolved_channel_scope_mode(
    channel_scope_mode: discord.app_commands.Choice[str] | None,
    channel_logins: str | None,
) -> ChannelScopeMode:
    if channel_scope_mode is not None:
        return ChannelScopeMode(channel_scope_mode.value)
    if split_csv_values(channel_logins):
        return ChannelScopeMode.ONLY_SELECTED
    return ChannelScopeMode.ALL_TRACKED


def _resolved_user_scope_mode(
    user_scope_mode: discord.app_commands.Choice[str] | None,
    user_logins: str | None,
) -> UserScopeMode:
    if user_scope_mode is not None:
        return UserScopeMode(user_scope_mode.value)
    if split_csv_values(user_logins):
        return UserScopeMode.ONLY_SELECTED
    return UserScopeMode.ALL_USERS
