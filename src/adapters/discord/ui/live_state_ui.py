"""Discord UI for configuring Twitch live/offline notifications."""

from __future__ import annotations

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordResultStyle
from src.localization import Localizer
from src.services.twitch_runtime import DISCORD_NOTIFY_ACTION, STREAM_OFFLINE_EVENT_KEY, STREAM_ONLINE_EVENT_KEY

from ..dispatch import dispatch_channel_event_command
from ..helpers import complete_bound_result, send_initial_result
from ..ui_data import AdapterEventActionPresentation, DiscordUIDataProvider, TrackedChannelPresentation
from .shared import BaseFormView, resolve_context_language, start_form


class LiveStateMenuView(BaseFormView):
    """Root `/live` menu for live and offline Discord notifications."""

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
        self.add_live.label = self.text("discord.live_state_ui.actions.add_live")
        self.add_offline.label = self.text("discord.live_state_ui.actions.add_offline")
        self.remove.label = self.text("discord.live_state_ui.actions.remove")
        self.disable.label = self.text("discord.live_state_ui.actions.disable")
        self.enable.label = self.text("discord.live_state_ui.actions.enable")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.live_state_ui.menu.title", "discord.live_state_ui.menu.message")

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def add_live(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_add_modal(interaction, STREAM_ONLINE_EVENT_KEY)

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def add_offline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_add_modal(interaction, STREAM_OFFLINE_EVENT_KEY)

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "remove")

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def disable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "disable")

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def enable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "enable")

    async def _open_add_modal(self, interaction: discord.Interaction, event_key: str) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="live",
            step="add",
            discord_channel_id=self._discord_channel_id,
        ):
            return
        tracked_channels = await self._data_provider.list_tracked_channels(self._discord_channel_id)
        if not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                self.result("discord.live_state_ui.errors.no_channels", style=DiscordResultStyle.ERROR),
            )
            return
        await interaction.response.send_modal(
            ChannelEventModal(
                title=self.text(f"discord.live_state_ui.modal.{event_key}.title"),
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                tracked_channels=tracked_channels,
                event_key=event_key,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )

    async def _open_action_modal(self, interaction: discord.Interaction, action: str) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._event_bus,
            flow="live",
            step=action,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        actions = [
            item
            for item in await self._data_provider.list_adapter_event_actions(self._discord_channel_id)
            if item.action.action_type == DISCORD_NOTIFY_ACTION
        ]
        if action == "disable":
            actions = [item for item in actions if not item.action.disabled]
        elif action == "enable":
            actions = [item for item in actions if item.action.disabled]
        if not actions:
            await self.finish_with_interaction(
                interaction,
                self.result(
                    f"discord.live_state_ui.errors.no_{action}_actions",
                    style=DiscordResultStyle.ERROR,
                ),
            )
            return
        await interaction.response.send_modal(
            ChannelEventActionModal(
                title=self.text(f"discord.live_state_ui.action.{action}_title"),
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action=action,
                actions=actions,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )


class ChannelEventModal(discord.ui.Modal):
    """Choose one tracked channel and configure one external channel event."""

    def __init__(
        self,
        *,
        title: str,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        tracked_channels: list[TrackedChannelPresentation],
        event_key: str,
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._event_key = event_key
        self._bound_message = bound_message
        state_text = localizer.text(f"discord.live_state_ui.states.{event_key}", language=language)
        self.channel = discord.ui.Label(
            text=localizer.text("discord.live_state_ui.modal.channel_label", language=language),
            description=localizer.text(
                "discord.live_state_ui.modal.channel_description",
                language=language,
                STATE=state_text,
            ),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.user_id,
                        description=channel.login[:100],
                    )
                    for channel in tracked_channels[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        result = await dispatch_channel_event_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action="add",
            twitch_channel_id=self.channel.component.values[0],
            event_key=self._event_key,
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ChannelEventActionModal(discord.ui.Modal):
    """Remove, disable, or enable one configured live/offline notification."""

    def __init__(
        self,
        *,
        title: str,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        actions: list[AdapterEventActionPresentation],
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.notification = discord.ui.Label(
            text=localizer.text("discord.live_state_ui.action.notification_label", language=language),
            description=localizer.text("discord.live_state_ui.action.notification_description", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_notification_label(item, localizer=localizer, language=language),
                        value=f"{item.event.event.subject_id}:{item.event.event.event_key}",
                        description=item.event.channel.login[:100],
                    )
                    for item in actions[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.notification)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        twitch_channel_id, event_key = self.notification.component.values[0].split(":", 1)
        result = await dispatch_channel_event_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action=self._action,
            twitch_channel_id=twitch_channel_id,
            event_key=event_key,
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


async def open_live_state_menu(
    interaction: discord.Interaction,
    *,
    event_bus: EventBus,
    ui_data_provider: DiscordUIDataProvider,
    localizer: Localizer,
) -> None:
    """Open the owner-bound `/live` management menu."""
    language = resolve_context_language(
        localizer=localizer,
        data_provider=ui_data_provider,
        discord_channel_id=interaction.channel_id,
    )
    if interaction.channel_id is None:
        await send_initial_result(
            interaction,
            localizer.result(
                "discord.live_state_ui.errors.command_unavailable",
                language=language,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            ),
        )
        return

    await start_form(
        interaction,
        view=LiveStateMenuView(
            owner_id=interaction.user.id,
            event_bus=event_bus,
            data_provider=ui_data_provider,
            discord_channel_id=interaction.channel_id,
            localizer=localizer,
        ),
    )


def _notification_label(
    item: AdapterEventActionPresentation,
    *,
    localizer: Localizer,
    language: str,
) -> str:
    state = localizer.text(f"discord.live_state_ui.states.{item.event.event.event_key}", language=language)
    return localizer.text(
        "discord.live_state_ui.action.notification_option",
        language=language,
        CHANNEL=item.event.channel.display_name,
        STATE=state,
    )[:100]
