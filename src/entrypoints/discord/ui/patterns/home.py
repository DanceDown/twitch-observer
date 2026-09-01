"""Home view for the guided ping add/edit flow."""

from __future__ import annotations

from typing import Protocol

import discord

from src.entrypoints.discord.helpers import defer_interaction_response
from src.events.commands import AddPatternCommand, EditPatternCommand
from src.events.discord_results import DiscordResultStyle
from src.events.pattern_scopes import ChannelScopeMode, OfflineScope, SubscriptionScope, UserScopeMode
from src.events.ui_flow import UIFlowKind, UIFlowStep

from ...dispatch import dispatch_add_pattern, dispatch_edit_pattern
from ...ui_data import TrackedChannelPresentation, TrackedUserPresentation
from ..shared import COLOR_PICKER_URL, BaseFormView
from .basics_modal import PatternBasicsModal
from .channels_modal import PatternChannelsModal
from .context import PatternViewContext
from .options_modal import PatternOptionsModal
from .state import PatternEditorMode, PatternFormState
from .text import channel_scope_text, offline_state_text, sub_state_text, user_scope_text
from .users_modal import PatternUsersModal


class PatternEditorDataProvider(Protocol):
    """Read-side data needed while editing ping channel/user scopes."""

    async def list_tracked_channels(self, discord_channel_id: int) -> list[TrackedChannelPresentation]:
        """Return tracked channels selectable in the pattern editor."""
        ...

    async def list_tracked_users(self, discord_channel_id: int) -> list[TrackedUserPresentation]:
        """Return tracked users selectable in the pattern editor."""
        ...


class PatternHomeView(BaseFormView):
    """Home screen for the guided ping add/edit flow."""

    def __init__(
        self,
        *,
        context: PatternViewContext[PatternEditorDataProvider],
        mode: PatternEditorMode,
        state: PatternFormState | None = None,
    ) -> None:
        """Create a pattern editor home view for add or edit mode."""
        super().__init__(
            owner_id=context.owner_id,
            localizer=context.localizer,
            language=context.language,
        )
        self._context = context
        self.mode = mode
        self.state = state or PatternFormState()
        self.basics.label = self.text("discord.pattern_ui.actions.basics")
        self.channels.label = self.text("discord.pattern_ui.actions.channels")
        self.users.label = self.text("discord.pattern_ui.actions.users")
        self.options.label = self.text("discord.pattern_ui.actions.options")
        self.save.label = self.text("discord.pattern_ui.actions.save")

    def render_embed(self) -> discord.Embed:
        """Render the current editor state as a localized summary embed."""
        lines = [
            self.text(
                "discord.pattern_ui.summary.text",
                sources={"view": {"text": self.state.pattern_text or self.text("discord.pattern_ui.summary.not_set")}},
            ),
            self.text(
                "discord.pattern_ui.summary.mode",
                sources={
                    "view": {
                        "mode": self.text(
                            "discord.pattern_ui.summary.mode_regex" if self.state.is_regex else "discord.pattern_ui.summary.mode_word"
                        )
                    }
                },
            ),
            self.text(
                "discord.pattern_ui.summary.where",
                sources={
                    "view": {
                        "value": channel_scope_text(
                            self._localizer,
                            self.language,
                            self.state.channel_scope_mode,
                            self.state.selected_channel_names,
                        )
                    }
                },
            ),
            self.text(
                "discord.pattern_ui.summary.who",
                sources={
                    "view": {
                        "value": user_scope_text(
                            self._localizer,
                            self.language,
                            self.state.user_scope_mode,
                            self.state.selected_user_names,
                        )
                    }
                },
            ),
            self.text(
                "discord.pattern_ui.summary.subscribers",
                sources={"view": {"value": sub_state_text(self._localizer, self.language, self.state.sub_state)}},
            ),
            self.text(
                "discord.pattern_ui.summary.stream_state",
                sources={"view": {"value": offline_state_text(self._localizer, self.language, self.state.offline_state)}},
            ),
            self.text(
                "discord.pattern_ui.summary.case_sensitive",
                sources={
                    "view": {
                        "value": self.text(
                            "discord.pattern_ui.summary.case_sensitive_yes"
                            if self.state.case_sensitive
                            else "discord.pattern_ui.summary.case_sensitive_no"
                        )
                    }
                },
            ),
            self.text(
                "discord.pattern_ui.summary.color",
                sources={"view": {"value": self.state.color or self.text("discord.pattern_ui.summary.color_inherited")}},
            ),
            self.text(
                "discord.pattern_ui.summary.priority",
                sources={
                    "view": {
                        "value": self.state.priority
                        if self.state.priority is not None
                        else self.text("discord.pattern_ui.summary.priority_auto")
                    }
                },
            ),
        ]
        result_key = "discord.pattern_ui.create_embed" if self.mode is PatternEditorMode.ADD else "discord.pattern_ui.edit_embed"
        return self.form_embed(
            result_key,
            sources={"view": {"summary_lines": lines, "color_picker_url": COLOR_PICKER_URL}},
        )

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def basics(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Open the modal for trigger text and regex mode."""
        if not await self.ensure_step_allowed(
            interaction,
            self._context.services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._context.discord_channel_id,
        ):
            return
        await self.open_modal(interaction, PatternBasicsModal(parent=self))

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def channels(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Open the modal for channel-scope settings."""
        if not await self.ensure_step_allowed(
            interaction,
            self._context.services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._context.discord_channel_id,
        ):
            return
        tracked_channels = await self._context.data_provider.list_tracked_channels(self._context.discord_channel_id)
        if not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.pattern_ui.errors.no_channels", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        await self.open_modal(interaction, PatternChannelsModal(parent=self, tracked_channels=tracked_channels))

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def users(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Open the modal for user-scope settings."""
        if not await self.ensure_step_allowed(
            interaction,
            self._context.services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._context.discord_channel_id,
        ):
            return
        tracked_users = await self._context.data_provider.list_tracked_users(self._context.discord_channel_id)
        if not tracked_users:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.pattern_ui.errors.no_users", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        await self.open_modal(interaction, PatternUsersModal(parent=self, tracked_users=tracked_users))

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def options(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Open the modal for stream/subscriber/color/priority options."""
        if not await self.ensure_step_allowed(
            interaction,
            self._context.services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._context.discord_channel_id,
        ):
            return
        await self.open_modal(interaction, PatternOptionsModal(parent=self))

    @discord.ui.button(label="_", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Validate the editor state and persist the pattern."""
        if not await self.ensure_step_allowed(
            interaction,
            self._context.services,
            flow=UIFlowKind.PATTERN,
            step=UIFlowStep.ROOT,
            discord_channel_id=self._context.discord_channel_id,
        ):
            return
        await defer_interaction_response(interaction, ephemeral=True)
        if self.state.channel_scope_mode in {"only_selected", "all_except_selected"} and not self.state.selected_channels:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.pattern_ui.errors.missing_selected_channels", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        if (
            self.state.user_scope_mode in {"only_selected", "all_except_selected", "all_tracked_except_selected"}
            and not self.state.selected_users
        ):
            await self.finish_with_interaction(
                interaction,
                self.result("discord.pattern_ui.errors.missing_selected_users", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
            return
        if self.mode is PatternEditorMode.ADD:
            result = await dispatch_add_pattern(
                self._context.services,
                AddPatternCommand(
                    discord_channel_id=self._context.discord_channel_id,
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
                ),
            )
        else:
            result = await dispatch_edit_pattern(
                self._context.services,
                EditPatternCommand(
                    discord_channel_id=self._context.discord_channel_id,
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
                ),
            )
        await self.finish_with_interaction(interaction, result)
