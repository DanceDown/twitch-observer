"""Discord UI for `/ping`."""

from __future__ import annotations

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.utils.discord_embeds import build_result_embed

from ..dispatch import dispatch_pattern_command, dispatch_pattern_edit_command
from ..ui_data import DiscordUIDataProvider, PatternPresentation, TrackedChannelPresentation, TrackedUserPresentation
from .patterns.text import channel_scope_text, offline_state_text, sub_state_text, user_scope_text
from .shared import COLOR_PICKER_URL, BaseFormView, PatternFormState, resolve_context_language


class PingMenuView(BaseFormView):
    """Root `/ping` flow routing into add/edit/remove/enable/disable paths."""

    def __init__(
        self,
        *,
        owner_id: int,
        event_bus: EventBus,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
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
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self.add.label = self.text("discord.pattern_ui.actions.add")
        self.edit.label = self.text("discord.pattern_ui.actions.edit")
        self.remove.label = self.text("discord.pattern_ui.actions.remove")
        self.disable.label = self.text("discord.pattern_ui.actions.disable")
        self.enable.label = self.text("discord.pattern_ui.actions.enable")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.pattern_ui.menu.title", "discord.pattern_ui.menu.message")

    @discord.ui.button(label="Add", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="ping",
            step="add",
            discord_channel_id=self._discord_channel_id,
        ):
            return
        view = PatternHomeView(
            owner_id=self.owner_id,
            event_bus=self._event_bus,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            action="add",
            localizer=self._localizer,
        )
        view.bound_message = self.bound_message
        await interaction.response.edit_message(embed=view.render_embed(), view=view)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="ping",
            step="edit",
            discord_channel_id=self._discord_channel_id,
        ):
            return
        view = PatternPickerView(
            owner_id=self.owner_id,
            event_bus=self._event_bus,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            localizer=self._localizer,
        )
        prepare_result = await view.prepare()
        if prepare_result is not None:
            await self.finish_with_interaction(interaction, prepare_result)
            return
        view.bound_message = self.bound_message
        await interaction.response.send_modal(
            PatternEditSelectionModal(
                parent=view,
                patterns=view._patterns,
                localizer=self._localizer,
                language=self.language,
            )
        )

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_id_action(interaction, "remove")

    @discord.ui.button(label="Disable", style=discord.ButtonStyle.secondary)
    async def disable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_id_action(interaction, "disable")

    @discord.ui.button(label="Enable", style=discord.ButtonStyle.secondary)
    async def enable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_id_action(interaction, "enable")

    async def _open_id_action(self, interaction: discord.Interaction, action: str) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="ping",
            step=action,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        view = PatternIdActionView(
            owner_id=self.owner_id,
            event_bus=self._event_bus,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            action=action,
            localizer=self._localizer,
        )
        prepare_result = await view.prepare()
        if prepare_result is not None:
            await self.finish_with_interaction(interaction, prepare_result)
            return
        view.bound_message = self.bound_message
        await interaction.response.send_modal(
            PatternActionSelectionModal(
                title={
                    "remove": self.text("discord.pattern_ui.action.remove_title"),
                    "disable": self.text("discord.pattern_ui.action.disable_title"),
                    "enable": self.text("discord.pattern_ui.action.enable_title"),
                }.get(action, self.text("discord.pattern_ui.action.choose_title")),
                parent=view,
                patterns=view._patterns,
                localizer=self._localizer,
                language=self.language,
            )
        )


class PatternIdActionView(BaseFormView):
    """Simple parameterless flows for ping remove/enable/disable actions."""

    def __init__(
        self,
        *,
        owner_id: int,
        event_bus: EventBus,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
        action: str,
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
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self._action = action
        self._patterns: list[PatternPresentation] = []

    async def prepare(self) -> DiscordCommandResult | None:
        patterns = await self._data_provider.list_patterns(self._discord_channel_id)
        if self._action == "disable":
            patterns = [pattern for pattern in patterns if not pattern.pattern.disabled]
        elif self._action == "enable":
            patterns = [pattern for pattern in patterns if pattern.pattern.disabled]
        self._patterns = patterns
        if not self._patterns:
            return DiscordCommandResult(
                title={
                    "disable": self.text("discord.pattern_ui.errors.no_enabled.title"),
                    "enable": self.text("discord.pattern_ui.errors.no_disabled.title"),
                }.get(self._action, self.text("discord.pattern_ui.errors.no_pings.title")),
                message={
                    "disable": self.text("discord.pattern_ui.errors.no_enabled.message"),
                    "enable": self.text("discord.pattern_ui.errors.no_disabled.message"),
                }.get(self._action, self.text("discord.pattern_ui.errors.no_pings.message")),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return None

    def render_embed(self) -> discord.Embed:
        action_label = {
            "remove": self.text("discord.pattern_ui.action.remove_title"),
            "disable": self.text("discord.pattern_ui.action.disable_title"),
            "enable": self.text("discord.pattern_ui.action.enable_title"),
        }.get(self._action, self.text("discord.pattern_ui.action.manage_title"))
        return self.form_embed(
            "discord.pattern_ui.action.embed_title",
            "discord.pattern_ui.action.embed_message",
            ACTION=action_label,
        )

    async def run_action(self, interaction: discord.Interaction, pattern_id: int) -> None:
        result = await dispatch_pattern_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=interaction.user.id,
            action=self._action,
            pattern_text=None,
            pattern_id=pattern_id,
            is_regex=None,
            channel_scope_mode="all_tracked",
            twitch_channel_logins=(),
            user_scope_mode="all_users",
            twitch_user_logins=(),
            sub_state="all",
            offline_state="both",
            case_sensitive=False,
            color=None,
            disabled=(self._action == "disable"),
        )
        await self.finish_with_interaction(interaction, result)


class PatternPickerView(BaseFormView):
    """First-step pattern picker that opens the full edit wizard."""

    def __init__(
        self,
        *,
        owner_id: int,
        event_bus: EventBus,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
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
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self._patterns: list[PatternPresentation] = []

    async def prepare(self) -> DiscordCommandResult | None:
        self._patterns = await self._data_provider.list_patterns(self._discord_channel_id)
        if not self._patterns:
            return DiscordCommandResult(
                title=self.text("discord.pattern_ui.errors.no_pings.title"),
                message=self.text("discord.pattern_ui.errors.no_pings.message"),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return None

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.pattern_ui.edit.title", "discord.pattern_ui.edit.message")

    async def submit_selection(self, interaction: discord.Interaction, pattern_id: int) -> None:
        pattern = await self._data_provider.get_pattern(self._discord_channel_id, pattern_id)
        if pattern is None:
            await interaction.response.defer()
            if self.bound_message is not None:
                await self.bound_message.edit(
                    embed=build_result_embed(
                        DiscordCommandResult(
                            title=self.text("discord.pattern_ui.errors.not_found.title"),
                            message=self.text("discord.pattern_ui.errors.not_found.message"),
                            style=DiscordResultStyle.ERROR,
                            ephemeral=True,
                        )
                    ),
                    view=None,
                )
            return
        state = PatternFormState(
            pattern_id=pattern.pattern.p_index,
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
        )
        view = PatternHomeView(
            owner_id=self.owner_id,
            event_bus=self._event_bus,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            action="edit",
            state=state,
            localizer=self._localizer,
        )
        view.bound_message = self.bound_message
        await interaction.response.defer()
        if self.bound_message is not None:
            await self.bound_message.edit(embed=view.render_embed(), view=view)


class PatternHomeView(BaseFormView):
    """Home screen for the guided ping add/edit flow."""

    def __init__(
        self,
        *,
        owner_id: int,
        event_bus: EventBus,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
        action: str,
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
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self._action = action
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
                MODE=self.text("discord.pattern_ui.summary.mode_regex" if self.state.is_regex else "discord.pattern_ui.summary.mode_ping"),
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
                VALUE=self.text("common.boolean.yes" if self.state.case_sensitive else "common.boolean.no"),
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
        title_key = "discord.pattern_ui.create.title" if self._action == "add" else "discord.pattern_ui.edit.title"
        return self.form_embed(
            title_key,
            "discord.pattern_ui.summary.embed_message",
            CONTENT="\n".join(lines),
            COLOR_PICKER_URL=COLOR_PICKER_URL,
        )

    @discord.ui.button(label="Basics", style=discord.ButtonStyle.primary)
    async def basics(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="ping",
            step="basics",
            discord_channel_id=self._discord_channel_id,
        ):
            return
        await interaction.response.send_modal(PatternBasicsModal(parent=self))

    @discord.ui.button(label="Channels", style=discord.ButtonStyle.secondary)
    async def channels(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="ping",
            step="channels",
            discord_channel_id=self._discord_channel_id,
        ):
            return
        tracked_channels = await self._data_provider.list_tracked_channels(self._discord_channel_id)
        if not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title=self.text("discord.pattern_ui.errors.no_channels.title"),
                    message=self.text("discord.pattern_ui.errors.no_channels.message"),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(PatternChannelsModal(parent=self, tracked_channels=tracked_channels))

    @discord.ui.button(label="Users", style=discord.ButtonStyle.secondary)
    async def users(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="ping",
            step="users",
            discord_channel_id=self._discord_channel_id,
        ):
            return
        tracked_users = await self._data_provider.list_tracked_users(self._discord_channel_id)
        if not tracked_users:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title=self.text("discord.pattern_ui.errors.no_users.title"),
                    message=self.text("discord.pattern_ui.errors.no_users.message"),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(PatternUsersModal(parent=self, tracked_users=tracked_users))

    @discord.ui.button(label="Options", style=discord.ButtonStyle.secondary)
    async def options(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="ping",
            step="options",
            discord_channel_id=self._discord_channel_id,
        ):
            return
        await interaction.response.send_modal(PatternOptionsModal(parent=self))

    @discord.ui.button(label="Save", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="ping",
            step="save",
            discord_channel_id=self._discord_channel_id,
        ):
            return
        if self._action == "add":
            result = await dispatch_pattern_command(
                self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action="add",
                pattern_text=self.state.pattern_text,
                pattern_id=None,
                is_regex=self.state.is_regex,
                channel_scope_mode=self.state.channel_scope_mode,
                twitch_channel_logins=tuple(self.state.selected_channels),
                user_scope_mode=self.state.user_scope_mode,
                twitch_user_logins=tuple(self.state.selected_users),
                sub_state=self.state.sub_state,
                offline_state=self.state.offline_state,
                case_sensitive=self.state.case_sensitive,
                color=self.state.color,
                disabled=False,
                priority=self.state.priority,
            )
        else:
            result = await dispatch_pattern_edit_command(
                self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                pattern_id=self.state.pattern_id or 0,
                pattern_text=self.state.pattern_text,
                is_regex=self.state.is_regex,
                channel_scope_mode=self.state.channel_scope_mode,
                twitch_channel_logins=tuple(self.state.selected_channels),
                user_scope_mode=self.state.user_scope_mode,
                twitch_user_logins=tuple(self.state.selected_users),
                sub_state=self.state.sub_state,
                offline_state=self.state.offline_state,
                case_sensitive=self.state.case_sensitive,
                color=self.state.color,
                clear_color=False,
                priority=self.state.priority,
            )
        await self.finish_with_interaction(interaction, result)


class PatternBasicsModal(discord.ui.Modal):
    """Collect text, mode, casing, and color in one modal."""

    def __init__(self, *, parent: PatternHomeView) -> None:
        super().__init__(title=parent.text("discord.pattern_ui.basics.title"), timeout=300)
        self._parent_view = parent
        self.pattern_text = discord.ui.TextInput(
            label=parent.text("discord.pattern_ui.basics.pattern_text_label"),
            placeholder=parent.text("discord.pattern_ui.basics.pattern_text_placeholder"),
            default=parent.state.pattern_text,
            required=True,
            style=discord.TextStyle.paragraph,
        )
        self.mode = discord.ui.Label(
            text=parent.text("discord.pattern_ui.basics.mode_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.mode_ping"),
                        value="ping",
                        default=not parent.state.is_regex,
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.mode_regex"),
                        value="regex",
                        default=parent.state.is_regex,
                    ),
                ]
            ),
        )
        self.case_sensitive = discord.ui.Label(
            text=parent.text("discord.pattern_ui.basics.extra_options_label"),
            description=parent.text("discord.pattern_ui.basics.extra_options_description"),
            component=discord.ui.CheckboxGroup(
                required=False,
                options=[
                    discord.CheckboxGroupOption(
                        label=parent.text("discord.pattern_ui.basics.case_sensitive_option"),
                        value="case_sensitive",
                        default=parent.state.case_sensitive,
                    )
                ],
            ),
        )
        self.color = discord.ui.TextInput(
            label=parent.text("discord.pattern_ui.basics.color_label"),
            placeholder=parent.text("discord.pattern_ui.basics.color_placeholder"),
            default=parent.state.color,
            required=False,
        )
        self.add_item(self.pattern_text)
        self.add_item(self.mode)
        self.add_item(self.case_sensitive)
        self.add_item(self.color)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._parent_view.state.pattern_text = self.pattern_text.value.strip()
        self._parent_view.state.is_regex = self.mode.component.value == "regex"
        self._parent_view.state.case_sensitive = "case_sensitive" in self.case_sensitive.component.values
        color_value = self.color.value.strip()
        self._parent_view.state.color = color_value or None
        await interaction.response.defer()
        await self._parent_view.rerender()


class PatternChannelsModal(discord.ui.Modal):
    """Collect the Twitch-channel scope for one ping."""

    def __init__(self, *, parent: PatternHomeView, tracked_channels: list[TrackedChannelPresentation]) -> None:
        super().__init__(title=parent.text("discord.pattern_ui.channels.title"), timeout=300)
        self._parent_view = parent
        self._tracked_channels = tracked_channels
        self.scope = discord.ui.Label(
            text=parent.text("discord.pattern_ui.channels.scope_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.channels.scope_all"),
                        value="all_tracked",
                        default=parent.state.channel_scope_mode == "all_tracked",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.channels.scope_only"),
                        value="only_selected",
                        default=parent.state.channel_scope_mode == "only_selected",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.channels.scope_except"),
                        value="all_except_selected",
                        default=parent.state.channel_scope_mode == "all_except_selected",
                    ),
                ]
            ),
        )
        self.channels = discord.ui.Label(
            text=parent.text("discord.pattern_ui.channels.tracked_label"),
            description=parent.text("discord.pattern_ui.channels.tracked_description"),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.login,
                        description=channel.login[:100],
                        default=channel.login in parent.state.selected_channels,
                    )
                    for channel in tracked_channels[:25]
                ],
                min_values=1,
                max_values=min(len(tracked_channels), 25),
                required=False,
            ),
        )
        self.add_item(self.scope)
        self.add_item(self.channels)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._parent_view.state.channel_scope_mode = self.scope.component.value
        if self.scope.component.value == "all_tracked":
            self._parent_view.state.selected_channels.clear()
            self._parent_view.state.selected_channel_names.clear()
        elif self.channels.component.values:
            self._parent_view.state.selected_channels = list(self.channels.component.values)
            name_by_login = {channel.login: channel.display_name for channel in self._tracked_channels}
            self._parent_view.state.selected_channel_names = [
                name_by_login.get(login, login) for login in self._parent_view.state.selected_channels
            ]
        await interaction.response.defer()
        await self._parent_view.rerender()


class PatternUsersModal(discord.ui.Modal):
    """Collect one user-scope update for one ping."""

    def __init__(self, *, parent: PatternHomeView, tracked_users: list[TrackedUserPresentation]) -> None:
        super().__init__(title=parent.text("discord.pattern_ui.users.title"), timeout=300)
        self._parent_view = parent
        self._tracked_users = tracked_users
        self.scope = discord.ui.Label(
            text=parent.text("discord.pattern_ui.users.scope_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_everyone"),
                        value="all_users",
                        default=parent.state.user_scope_mode == "all_users",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_all_tracked"),
                        value="all_tracked",
                        default=parent.state.user_scope_mode == "all_tracked",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_all_tracked_except"),
                        value="all_tracked_except_selected",
                        default=parent.state.user_scope_mode == "all_tracked_except_selected",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_only"),
                        value="only_selected",
                        default=parent.state.user_scope_mode == "only_selected",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.users.scope_everyone_except"),
                        value="all_except_selected",
                        default=parent.state.user_scope_mode == "all_except_selected",
                    ),
                ]
            ),
        )
        self.users = discord.ui.Label(
            text=parent.text("discord.pattern_ui.users.tracked_label"),
            description=parent.text("discord.pattern_ui.users.tracked_description"),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=user.display_name[:100],
                        value=user.login,
                        description=user.login[:100],
                        default=user.login in parent.state.selected_users,
                    )
                    for user in tracked_users[:25]
                ],
                min_values=1,
                max_values=min(len(tracked_users), 25),
                required=False,
            ),
        )
        self.add_item(self.scope)
        self.add_item(self.users)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = self._parent_view.state
        state.user_scope_mode = self.scope.component.value
        if state.user_scope_mode in {"all_users", "all_tracked"}:
            state.selected_users.clear()
            state.selected_user_names.clear()
        elif self.users.component.values:
            state.selected_users = list(self.users.component.values)
            name_by_login = {user.login: user.display_name for user in self._tracked_users}
            state.selected_user_names = [name_by_login.get(login, login) for login in state.selected_users]
        await interaction.response.defer()
        await self._parent_view.rerender()


class PatternOptionsModal(discord.ui.Modal):
    """Collect the remaining non-text match options for one ping."""

    def __init__(self, *, parent: PatternHomeView) -> None:
        super().__init__(title=parent.text("discord.pattern_ui.options.title"), timeout=300)
        self._parent_view = parent
        self.sub_state = discord.ui.Label(
            text=parent.text("discord.pattern_ui.options.sub_state_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.sub_state_all"),
                        value="all",
                        default=parent.state.sub_state == "all",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.sub_state_subs"),
                        value="subs",
                        default=parent.state.sub_state == "subs",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.sub_state_non_subs"),
                        value="non_subs",
                        default=parent.state.sub_state == "non_subs",
                    ),
                ]
            ),
        )
        self.offline_state = discord.ui.Label(
            text=parent.text("discord.pattern_ui.options.offline_state_label"),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.offline_state_both"),
                        value="both",
                        default=parent.state.offline_state == "both",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.offline_state_online"),
                        value="online",
                        default=parent.state.offline_state == "online",
                    ),
                    discord.RadioGroupOption(
                        label=parent.text("discord.pattern_ui.summary.offline_state_offline"),
                        value="offline",
                        default=parent.state.offline_state == "offline",
                    ),
                ]
            ),
        )
        priority_default = "" if parent.state.priority is None else str(parent.state.priority)
        self.priority = discord.ui.TextInput(
            label=parent.text("discord.pattern_ui.options.priority_label"),
            placeholder=parent.text("discord.pattern_ui.options.priority_placeholder"),
            default=priority_default,
            required=False,
        )
        self.add_item(self.sub_state)
        self.add_item(self.offline_state)
        self.add_item(self.priority)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._parent_view.state.sub_state = self.sub_state.component.value
        self._parent_view.state.offline_state = self.offline_state.component.value
        normalized = self.priority.value.strip()
        if normalized:
            try:
                parsed = int(normalized)
            except ValueError:
                await self._parent_view.finish_with_interaction(
                    interaction,
                    DiscordCommandResult(
                        title=self._parent_view.text("discord.pattern_ui.errors.invalid_priority.title"),
                        message=self._parent_view.text("discord.pattern_ui.errors.invalid_priority.message"),
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )
                return
            if parsed < 0 or parsed > 9:
                await self._parent_view.finish_with_interaction(
                    interaction,
                    DiscordCommandResult(
                        title=self._parent_view.text("discord.pattern_ui.errors.invalid_priority.title"),
                        message=self._parent_view.text("discord.pattern_ui.errors.invalid_priority.message"),
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )
                return
            self._parent_view.state.priority = parsed
        elif self._parent_view._action == "edit":
            self._parent_view.state.priority = None
        await interaction.response.defer()
        await self._parent_view.rerender()


class PatternEditSelectionModal(discord.ui.Modal):
    """Choose one existing ping and then open the edit wizard."""

    def __init__(
        self,
        *,
        parent: PatternPickerView,
        patterns: list[PatternPresentation],
        localizer: Localizer,
        language: str,
    ) -> None:
        super().__init__(title=localizer.text("discord.pattern_ui.selection.choose_title", language=language), timeout=300)
        self._parent_view = parent
        self.pattern = discord.ui.Label(
            text=localizer.text("discord.pattern_ui.selection.edit_label", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=(item.pattern.regex or localizer.text("discord.pattern_ui.selection.untitled_ping", language=language))[:100],
                        value=str(item.pattern.p_index),
                        description=localizer.text(
                            "discord.pattern_ui.selection.option_description",
                            language=language,
                            TYPE=localizer.text(
                                (
                                    "discord.pattern_ui.summary.mode_regex"
                                    if item.pattern.is_regex
                                    else "discord.pattern_ui.summary.mode_ping"
                                ),
                                language=language,
                            ),
                        ),
                    )
                    for item in patterns[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.pattern)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._parent_view.submit_selection(interaction, int(self.pattern.component.values[0]))


class PatternActionSelectionModal(discord.ui.Modal):
    """Choose one ping to remove, enable, or disable."""

    def __init__(
        self,
        *,
        title: str,
        parent: PatternIdActionView,
        patterns: list[PatternPresentation],
        localizer: Localizer,
        language: str,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._parent_view = parent
        self.pattern = discord.ui.Label(
            text=localizer.text("discord.pattern_ui.selection.update_label", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=(item.pattern.regex or localizer.text("discord.pattern_ui.selection.untitled_ping", language=language))[:100],
                        value=str(item.pattern.p_index),
                        description=localizer.text(
                            "discord.pattern_ui.selection.option_description",
                            language=language,
                            TYPE=localizer.text(
                                (
                                    "discord.pattern_ui.summary.mode_regex"
                                    if item.pattern.is_regex
                                    else "discord.pattern_ui.summary.mode_ping"
                                ),
                                language=language,
                            ),
                        ),
                    )
                    for item in patterns[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.pattern)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._parent_view.run_action(interaction, int(self.pattern.component.values[0]))
