"""Home view for the guided ping add/edit flow."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
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

from ...dispatch import dispatch_add_pattern, dispatch_edit_pattern
from ...ui_data import DiscordUIDataProvider
from ..shared import COLOR_PICKER_URL, BaseFormView, resolve_context_language
from .basics_modal import PatternBasicsModal
from .channels_modal import PatternChannelsModal
from .options_modal import PatternOptionsModal
from .state import PatternEditorMode, PatternFormState
from .text import channel_scope_text, offline_state_text, sub_state_text, user_scope_text
from .users_modal import PatternUsersModal


class PatternHomeView(BaseFormView):
    """Home screen for the guided ping add/edit flow."""

    def __init__(
        self,
        *,
        owner_id: int,
        services: DiscordServiceBundle,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
        mode: PatternEditorMode,
        state: PatternFormState | None = None,
        localizer: Localizer,
    ) -> None:
        super().__init__(
            owner_id=owner_id,
            localizer=localizer,
            language=resolve_context_language(
                localizer=localizer,
                data_provider=data_provider,
                discord_channel_id=discord_channel_id,
            ),
        )
        self._services = services
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self.mode = mode
        self.state = state or PatternFormState()
        self.basics.label = self.text("discord.pattern_ui.actions.basics")
        self.channels.label = self.text("discord.pattern_ui.actions.channels")
        self.users.label = self.text("discord.pattern_ui.actions.users")
        self.options.label = self.text("discord.pattern_ui.actions.options")
        self.save.label = self.text("discord.pattern_ui.actions.save")

    def render_embed(self) -> discord.Embed:
        lines = [
            self.text("discord.pattern_ui.summary.text", TEXT=self.state.pattern_text or self.text("discord.pattern_ui.summary.not_set")),
            self.text(
                "discord.pattern_ui.summary.mode",
                PING_MODE=self.text(
                    "discord.pattern_ui.summary.mode_regex"
                    if self.state.is_regex
                    else "discord.pattern_ui.summary.mode_word"
                ),
            ),
            self.text(
                "discord.pattern_ui.summary.where",
                VALUE=channel_scope_text(
                    self._localizer,
                    self.language,
                    self.state.channel_scope_mode,
                    self.state.selected_channel_names,
                ),
            ),
            self.text(
                "discord.pattern_ui.summary.who",
                VALUE=user_scope_text(
                    self._localizer,
                    self.language,
                    self.state.user_scope_mode,
                    self.state.selected_user_names,
                ),
            ),
            self.text(
                "discord.pattern_ui.summary.subscribers",
                VALUE=sub_state_text(self._localizer, self.language, self.state.sub_state),
            ),
            self.text(
                "discord.pattern_ui.summary.stream_state",
                VALUE=offline_state_text(self._localizer, self.language, self.state.offline_state),
            ),
            self.text(
                "discord.pattern_ui.summary.case_sensitive",
                VALUE=self.text(
                    "discord.pattern_ui.summary.case_sensitive_yes"
                    if self.state.case_sensitive
                    else "discord.pattern_ui.summary.case_sensitive_no"
                ),
            ),
            self.text(
                "discord.pattern_ui.summary.color",
                VALUE=self.state.color or self.text("discord.pattern_ui.summary.color_inherited"),
            ),
            self.text(
                "discord.pattern_ui.summary.priority",
                VALUE=self.state.priority if self.state.priority is not None else self.text("discord.pattern_ui.summary.priority_auto"),
            ),
        ]
        result_key = (
            "discord.pattern_ui.create_embed"
            if self.mode is PatternEditorMode.ADD
            else "discord.pattern_ui.edit_embed"
        )
        return self.form_embed(result_key, SUMMARY_LINES=lines, COLOR_PICKER_URL=COLOR_PICKER_URL)

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def basics(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        await interaction.response.send_modal(PatternBasicsModal(parent=self))

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def channels(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        tracked_channels = await self._data_provider.list_tracked_channels(self._discord_channel_id)
        if not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.pattern_ui.errors.no_channels", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        await interaction.response.send_modal(PatternChannelsModal(parent=self, tracked_channels=tracked_channels))

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def users(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        tracked_users = await self._data_provider.list_tracked_users(self._discord_channel_id)
        if not tracked_users:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.pattern_ui.errors.no_users", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        await interaction.response.send_modal(PatternUsersModal(parent=self, tracked_users=tracked_users))

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def options(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        await interaction.response.send_modal(PatternOptionsModal(parent=self))

    @discord.ui.button(label="_", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        if self.state.channel_scope_mode in {"only_selected", "all_except_selected"} and not self.state.selected_channels:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.pattern_ui.errors.missing_selected_channels", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        if self.state.user_scope_mode in {"only_selected", "all_except_selected", "all_tracked_except_selected"} and not self.state.selected_users:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.pattern_ui.errors.missing_selected_users", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        if self.mode is PatternEditorMode.ADD:
            result = await dispatch_add_pattern(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                pattern_text=self.state.pattern_text or "",
                is_regex=self.state.is_regex,
                channel_scope_mode=ChannelScopeMode(self.state.channel_scope_mode),
                twitch_channel_logins=tuple(self.state.selected_channels),
                user_scope_mode=UserScopeMode(self.state.user_scope_mode),
                twitch_user_logins=tuple(self.state.selected_users),
                sub_state=SubscriptionScope(self.state.sub_state),
                offline_state=OfflineScope(self.state.offline_state),
                case_sensitive=self.state.case_sensitive,
                color=self.state.color,
                disabled=False,
                priority=self.state.priority,
            )
        else:
            result = await dispatch_edit_pattern(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                pattern_id=self.state.pattern_id or 0,
                pattern_text=self.state.pattern_text,
                is_regex=self.state.is_regex,
                channel_scope_mode=ChannelScopeMode(self.state.channel_scope_mode),
                twitch_channel_logins=tuple(self.state.selected_channels),
                user_scope_mode=UserScopeMode(self.state.user_scope_mode),
                twitch_user_logins=tuple(self.state.selected_users),
                sub_state=SubscriptionScope(self.state.sub_state),
                offline_state=OfflineScope(self.state.offline_state),
                case_sensitive=self.state.case_sensitive,
                color=self.state.color,
                clear_color=False,
                priority=self.state.priority,
            )
        await self.finish_with_interaction(interaction, result)
