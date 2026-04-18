from __future__ import annotations

"""Discord UI for `/ping`."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.utils.discord_embeds import build_result_embed

from ..dispatch import dispatch_pattern_command, dispatch_pattern_edit_command
from ..ui_data import DiscordUIDataProvider, PatternPresentation, TrackedChannelPresentation, TrackedUserPresentation
from .shared import BaseFormView, COLOR_PICKER_URL, PatternFormState, build_form_embed


def _channel_scope_text(mode: str, selected: list[str]) -> str:
    """Render one human-friendly summary for the channel scope."""
    if mode == "all_tracked":
        return "All tracked Twitch channels"
    if mode == "only_selected":
        return f"Only: {', '.join(selected)}" if selected else "Only selected channels"
    if mode == "all_except_selected":
        return f"All except: {', '.join(selected)}" if selected else "All except selected channels"
    return mode


def _user_scope_text(mode: str, selected: list[str]) -> str:
    """Render one human-friendly summary for the user scope."""
    if mode == "all_users":
        return "Everyone"
    if mode == "all_tracked":
        return "All tracked Twitch users"
    if mode == "all_tracked_except_selected":
        return (
            f"All tracked except: {', '.join(selected)}"
            if selected
            else "All tracked except selected Twitch names"
        )
    if mode == "only_selected":
        return f"Only: {', '.join(selected)}" if selected else "Only selected Twitch names"
    if mode == "all_except_selected":
        return f"Everyone except: {', '.join(selected)}" if selected else "Everyone except selected Twitch names"
    return mode


def _sub_state_text(value: str) -> str:
    """Render the subscriber scope in friendly language."""
    return {
        "all": "Everyone",
        "subs": "Subscribers only",
        "non_subs": "Non-subscribers only",
    }.get(value, value)


def _offline_state_text(value: str) -> str:
    """Render the stream-state filter in friendly language."""
    return {
        "both": "Online and offline",
        "online": "Only while live",
        "offline": "Only while offline",
    }.get(value, value)


class PingMenuView(BaseFormView):
    """Root `/ping` flow routing into add/edit/remove/enable/disable paths."""

    def __init__(
        self,
        *,
        owner_id: int,
        event_bus: EventBus,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
    ) -> None:
        super().__init__(owner_id=owner_id)
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id

    def render_embed(self) -> discord.Embed:
        return build_form_embed(
            "Pings",
            "Create a new ping, edit an existing one, or disable/enable it.",
        )

    @discord.ui.button(label="Add", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        view = PatternHomeView(
            owner_id=self.owner_id,
            event_bus=self._event_bus,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            action="add",
        )
        view.bound_message = self.bound_message
        await interaction.response.edit_message(embed=view.render_embed(), view=view)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        view = PatternPickerView(
            owner_id=self.owner_id,
            event_bus=self._event_bus,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
        )
        prepare_result = await view.prepare()
        if prepare_result is not None:
            await self.finish_with_interaction(interaction, prepare_result)
            return
        view.bound_message = self.bound_message
        await interaction.response.send_modal(PatternEditSelectionModal(parent=view, patterns=view._patterns))

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
        view = PatternIdActionView(
            owner_id=self.owner_id,
            event_bus=self._event_bus,
            data_provider=self._data_provider,
            discord_channel_id=self._discord_channel_id,
            action=action,
        )
        prepare_result = await view.prepare()
        if prepare_result is not None:
            await self.finish_with_interaction(interaction, prepare_result)
            return
        view.bound_message = self.bound_message
        await interaction.response.send_modal(
            PatternActionSelectionModal(
                title={
                    "remove": "Remove Ping",
                    "disable": "Disable Ping",
                    "enable": "Enable Ping",
                }.get(action, "Choose Ping"),
                parent=view,
                patterns=view._patterns,
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
    ) -> None:
        super().__init__(owner_id=owner_id)
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
                    "disable": "No Enabled Pings",
                    "enable": "No Disabled Pings",
                }.get(self._action, "No Pings Yet"),
                message={
                    "disable": "There are no enabled pings to disable.",
                    "enable": "There are no disabled pings to enable.",
                }.get(self._action, "There are no pings yet."),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return None

    def render_embed(self) -> discord.Embed:
        action_label = {
            "remove": "Remove Ping",
            "disable": "Disable Ping",
            "enable": "Enable Ping",
        }.get(self._action, "Manage Ping")
        return build_form_embed(
            action_label,
            "Choose the ping you want to update.",
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
    ) -> None:
        super().__init__(owner_id=owner_id)
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self._patterns: list[PatternPresentation] = []

    async def prepare(self) -> DiscordCommandResult | None:
        self._patterns = await self._data_provider.list_patterns(self._discord_channel_id)
        if not self._patterns:
            return DiscordCommandResult(
                title="No Pings Yet",
                message="There are no pings yet.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return None

    def render_embed(self) -> discord.Embed:
        return build_form_embed(
            "Edit Ping",
            "Choose the ping you want to change.",
        )

    async def submit_selection(self, interaction: discord.Interaction, pattern_id: int) -> None:
        pattern = await self._data_provider.get_pattern(self._discord_channel_id, pattern_id)
        if pattern is None:
            await interaction.response.defer()
            if self.bound_message is not None:
                await self.bound_message.edit(
                    embed=build_result_embed(
                        DiscordCommandResult(
                            title="Ping Not Found",
                            message="The selected ping no longer exists.",
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
            user_scope_mode=pattern.pattern.user_scope_mode,
            selected_users=list(pattern.user_logins),
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
    ) -> None:
        super().__init__(owner_id=owner_id)
        self._event_bus = event_bus
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self._action = action
        self.state = state or PatternFormState()

    def render_embed(self) -> discord.Embed:
        lines = [
            f"Text: `{self.state.pattern_text or 'not set yet'}`",
            f"Mode: `{'Regex' if self.state.is_regex else 'Normal ping'}`",
            f"Where: `{_channel_scope_text(self.state.channel_scope_mode, self.state.selected_channels)}`",
            f"Who: `{_user_scope_text(self.state.user_scope_mode, self.state.selected_users)}`",
            f"Subscribers: `{_sub_state_text(self.state.sub_state)}`",
            f"Stream state: `{_offline_state_text(self.state.offline_state)}`",
            f"Case sensitive: `{'Yes' if self.state.case_sensitive else 'No'}`",
            f"Color: `{self.state.color or 'Inherited automatically'}`",
            f"Priority: `{self.state.priority if self.state.priority is not None else 'Automatic'}`",
        ]
        return build_form_embed(
            "New Ping" if self._action == "add" else "Edit Ping",
            (
                "\n".join(lines)
                + "\n\nUse the buttons below to fill out each section."
                + f"\nNeed a hex color? [Open color picker]({COLOR_PICKER_URL})"
            ),
        )

    @discord.ui.button(label="Basics", style=discord.ButtonStyle.primary)
    async def basics(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(PatternBasicsModal(parent=self))

    @discord.ui.button(label="Channels", style=discord.ButtonStyle.secondary)
    async def channels(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        tracked_channels = await self._data_provider.list_tracked_channels(self._discord_channel_id)
        if not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title="No Channels",
                    message="Add at least one Twitch channel first before narrowing a ping to specific channels.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(PatternChannelsModal(parent=self, tracked_channels=tracked_channels))

    @discord.ui.button(label="Users", style=discord.ButtonStyle.secondary)
    async def users(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        tracked_users = await self._data_provider.list_tracked_users(self._discord_channel_id)
        if not tracked_users:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title="No Tracked Users",
                    message="Add Twitch users with `/user` before narrowing a ping to specific users.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(PatternUsersModal(parent=self, tracked_users=tracked_users))

    @discord.ui.button(label="Options", style=discord.ButtonStyle.secondary)
    async def options(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(PatternOptionsModal(parent=self))

    @discord.ui.button(label="Save", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
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


class PatternBasicsModal(discord.ui.Modal, title="Ping Basics"):
    """Collect text, mode, casing, and color in one modal."""

    def __init__(self, *, parent: PatternHomeView) -> None:
        super().__init__(timeout=300)
        self._parent_view = parent
        self.pattern_text = discord.ui.TextInput(
            label="What should I look for?",
            placeholder="e.g. your name",
            default=parent.state.pattern_text,
            required=True,
            style=discord.TextStyle.paragraph,
        )
        self.mode = discord.ui.Label(
            text="How should it match?",
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(label="Normal ping", value="ping", default=not parent.state.is_regex),
                    discord.RadioGroupOption(label="Regex", value="regex", default=parent.state.is_regex),
                ]
            ),
        )
        self.case_sensitive = discord.ui.Label(
            text="Extra options",
            description="Turn this on only when upper/lowercase should matter.",
            component=discord.ui.CheckboxGroup(
                required=False,
                options=[
                    discord.CheckboxGroupOption(
                        label="Case sensitive",
                        value="case_sensitive",
                        default=parent.state.case_sensitive,
                    )
                ],
            ),
        )
        self.color = discord.ui.TextInput(
            label="Color",
            placeholder="e.g. #9146FF",
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


class PatternChannelsModal(discord.ui.Modal, title="Where Should It Match?"):
    """Collect the Twitch-channel scope for one ping."""

    def __init__(self, *, parent: PatternHomeView, tracked_channels: list[TrackedChannelPresentation]) -> None:
        super().__init__(timeout=300)
        self._parent_view = parent
        self.scope = discord.ui.Label(
            text="Channel scope",
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(label="Every tracked channel", value="all_tracked", default=parent.state.channel_scope_mode == "all_tracked"),
                    discord.RadioGroupOption(label="Only these channels", value="only_selected", default=parent.state.channel_scope_mode == "only_selected"),
                    discord.RadioGroupOption(label="Every channel except these", value="all_except_selected", default=parent.state.channel_scope_mode == "all_except_selected"),
                ]
            ),
        )
        self.channels = discord.ui.Label(
            text="Tracked Twitch channels",
            description="Choose channels only when you use one of the selected-channel scopes.",
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.login,
                        description=channel.login[:100],
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
        elif self.channels.component.values:
            self._parent_view.state.selected_channels = list(self.channels.component.values)
        await interaction.response.defer()
        await self._parent_view.rerender()


class PatternUsersModal(discord.ui.Modal, title="Who Can Trigger It?"):
    """Collect one user-scope update for one ping."""

    def __init__(self, *, parent: PatternHomeView, tracked_users: list[TrackedUserPresentation]) -> None:
        super().__init__(timeout=300)
        self._parent_view = parent
        self.scope = discord.ui.Label(
            text="Twitch name scope",
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(label="Everyone", value="all_users", default=parent.state.user_scope_mode == "all_users"),
                    discord.RadioGroupOption(label="All tracked Twitch users", value="all_tracked", default=parent.state.user_scope_mode == "all_tracked"),
                    discord.RadioGroupOption(
                        label="All tracked except selected names",
                        value="all_tracked_except_selected",
                        default=parent.state.user_scope_mode == "all_tracked_except_selected",
                    ),
                    discord.RadioGroupOption(label="Only selected names", value="only_selected", default=parent.state.user_scope_mode == "only_selected"),
                    discord.RadioGroupOption(label="Everyone except selected names", value="all_except_selected", default=parent.state.user_scope_mode == "all_except_selected"),
                ]
            ),
        )
        self.users = discord.ui.Label(
            text="Tracked Twitch users",
            description="Choose users only when you use one of the selected-user scopes.",
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=user.display_name[:100],
                        value=user.login,
                        description=user.login[:100],
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
        elif self.users.component.values:
            state.selected_users = list(self.users.component.values)
        await interaction.response.defer()
        await self._parent_view.rerender()


class PatternOptionsModal(discord.ui.Modal, title="Ping Options"):
    """Collect the remaining non-text match options for one ping."""

    def __init__(self, *, parent: PatternHomeView) -> None:
        super().__init__(timeout=300)
        self._parent_view = parent
        self.sub_state = discord.ui.Label(
            text="Who should count as a match?",
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(label="Everyone", value="all", default=parent.state.sub_state == "all"),
                    discord.RadioGroupOption(label="Subscribers only", value="subs", default=parent.state.sub_state == "subs"),
                    discord.RadioGroupOption(label="Non-subscribers only", value="non_subs", default=parent.state.sub_state == "non_subs"),
                ]
            ),
        )
        self.offline_state = discord.ui.Label(
            text="When should it trigger?",
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(label="Online and offline", value="both", default=parent.state.offline_state == "both"),
                    discord.RadioGroupOption(label="Only while live", value="online", default=parent.state.offline_state == "online"),
                    discord.RadioGroupOption(label="Only while offline", value="offline", default=parent.state.offline_state == "offline"),
                ]
            ),
        )
        priority_default = "" if parent.state.priority is None else str(parent.state.priority)
        self.priority = discord.ui.TextInput(
            label="Priority",
            placeholder="Leave empty to keep the default order",
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
                        title="Invalid Priority",
                        message="Priority must be a whole number between `0` and `9`.",
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )
                return
            if parsed < 0 or parsed > 9:
                await self._parent_view.finish_with_interaction(
                    interaction,
                    DiscordCommandResult(
                        title="Invalid Priority",
                        message="Priority must be a whole number between `0` and `9`.",
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


class PatternEditSelectionModal(discord.ui.Modal, title="Choose Ping"):
    """Choose one existing ping and then open the edit wizard."""

    def __init__(self, *, parent: PatternPickerView, patterns: list[PatternPresentation]) -> None:
        super().__init__(timeout=300)
        self._parent_view = parent
        self.pattern = discord.ui.Label(
            text="Which ping do you want to edit?",
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=(item.pattern.regex or "Untitled ping")[:100],
                        value=str(item.pattern.p_index),
                        description=("Regex" if item.pattern.is_regex else "Ping"),
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

    def __init__(self, *, title: str, parent: PatternIdActionView, patterns: list[PatternPresentation]) -> None:
        super().__init__(title=title, timeout=300)
        self._parent_view = parent
        self.pattern = discord.ui.Label(
            text="Which ping do you want to update?",
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=(item.pattern.regex or "Untitled ping")[:100],
                        value=str(item.pattern.p_index),
                        description=("Regex" if item.pattern.is_regex else "Ping"),
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
