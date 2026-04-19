from __future__ import annotations

"""Discord UI for `/reply`."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle

from ..dispatch import dispatch_reply_command
from ..helpers import complete_bound_result, normalize_optional_text, send_initial_result
from ..ui_data import (
    ChannelEventReplyPresentation,
    DiscordUIDataProvider,
    PatternPresentation,
    ReplyPresentation,
    TrackedChannelPresentation,
)
from .shared import BaseFormView, build_form_embed


def _pattern_label(pattern: PatternPresentation) -> str:
    """Build a compact human-readable label for one pattern option."""
    return (pattern.pattern.regex or "Untitled ping")[:100]


def _reply_label(reply: ReplyPresentation) -> str:
    """Build a compact human-readable label for one reply option."""
    return reply.reply.reply_message[:100]


def _channel_event_label(channel: TrackedChannelPresentation, event_state: str) -> str:
    state_label = "Online" if event_state == "online" else "Offline"
    return f"{channel.display_name} {state_label}"[:100]


def _encode_pattern_target(pattern_id: int) -> str:
    return f"pattern:{pattern_id}"


def _encode_channel_event_target(channel_id: str, event_state: str) -> str:
    return f"channel_event:{channel_id}:{event_state}"


def _decode_target(value: str) -> tuple[str, int | None, str | None, str | None]:
    if value.startswith("pattern:"):
        return "pattern", int(value.split(":", 1)[1]), None, None
    _, twitch_channel_id, event_state = value.split(":", 2)
    return "channel_event", None, twitch_channel_id, event_state


class ReplyAddModal(discord.ui.Modal, title="Add Auto-Reply"):
    """Attach one reply to one existing pattern using a modal."""

    message = discord.ui.TextInput(
        label="What should it say?",
        style=discord.TextStyle.paragraph,
        placeholder="Hello {NAME}!",
        required=True,
        max_length=500,
    )

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        patterns: list[PatternPresentation],
        tracked_channels: list[TrackedChannelPresentation],
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        self.pattern = discord.ui.Label(
            text="Trigger",
            description="Choose either a ping/regex pattern or a tracked channel live/offline event.",
            component=discord.ui.Select(
                options=(
                    [
                        discord.SelectOption(
                            label=_pattern_label(pattern),
                            value=_encode_pattern_target(pattern.pattern.p_index),
                            description=f"ID {pattern.pattern.p_index} - {'Regex' if pattern.pattern.is_regex else 'Ping'}",
                        )
                        for pattern in patterns
                    ]
                    + [
                        discord.SelectOption(
                            label=_channel_event_label(channel, "online"),
                            value=_encode_channel_event_target(channel.user_id, "online"),
                            description=f"{channel.login[:80]} - when the channel goes live",
                        )
                        for channel in tracked_channels
                    ]
                    + [
                        discord.SelectOption(
                            label=_channel_event_label(channel, "offline"),
                            value=_encode_channel_event_target(channel.user_id, "offline"),
                            description=f"{channel.login[:80]} - when the channel goes offline",
                        )
                        for channel in tracked_channels
                    ]
                )[:25],
                min_values=1,
                max_values=1,
            ),
        )
        self.mode = discord.ui.Label(
            text="Reply Mode",
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(label="Send as normal chat message", value="message", default=True),
                    discord.RadioGroupOption(label="Reply to the matched message", value="reply"),
                ]
            ),
        )
        self.add_item(self.pattern)
        self.add_item(self.mode)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Create one auto-reply attached to the chosen pattern."""
        target_type, pattern_id, twitch_channel_id, channel_event_state = _decode_target(self.pattern.component.values[0])
        result = await dispatch_reply_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action="add",
            pattern_id=0 if pattern_id is None else pattern_id,
            message=normalize_optional_text(self.message.value),
            reply_as_reply=self.mode.component.value == "reply",
            target_type=target_type,
            twitch_channel_id=twitch_channel_id,
            channel_event_state=channel_event_state,
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ReplyActionModal(discord.ui.Modal):
    """Enable, disable, or remove one existing reply via a modal."""

    def __init__(
        self,
        *,
        title: str,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        replies: list[ReplyPresentation | ChannelEventReplyPresentation],
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.reply = discord.ui.Label(
            text="Auto-Reply",
            description="Choose the automatic reply you want to update.",
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_reply_label(reply),
                        value=_encode_pattern_target(reply.reply.p_index),
                        description=f"Linked to: {_pattern_label(reply.pattern)}",
                    )
                    if isinstance(reply, ReplyPresentation)
                    else discord.SelectOption(
                        label=reply.reply.reply_message[:100],
                        value=_encode_channel_event_target(reply.reply.twitch_channel_id, reply.reply.event_state),
                        description=f"Linked to: {_channel_event_label(reply.channel, reply.reply.event_state)}",
                    )
                    for reply in replies
                ][:25],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.reply)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the selected reply action."""
        target_type, pattern_id, twitch_channel_id, channel_event_state = _decode_target(self.reply.component.values[0])
        result = await dispatch_reply_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action=self._action,
            pattern_id=0 if pattern_id is None else pattern_id,
            message=None,
            reply_as_reply=False,
            target_type=target_type,
            twitch_channel_id=twitch_channel_id,
            channel_event_state=channel_event_state,
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ReplyMenuView(BaseFormView):
    """Root `/reply` flow with one button per action."""

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
            "Auto-Replies",
            "Attach an automatic message to a ping or to a tracked channel going live/offline, then manage those replies here.",
        )

    @discord.ui.button(label="Add", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        patterns = await self._data_provider.list_patterns(self._discord_channel_id)
        tracked_channels = await self._data_provider.list_tracked_channels(self._discord_channel_id)
        if not patterns and not tracked_channels:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title="Nothing Available Yet",
                    message="Create a ping or track a channel first before attaching an auto-reply.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(
            ReplyAddModal(
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                patterns=patterns,
                tracked_channels=tracked_channels,
                bound_message=self.bound_message,
            )
        )

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "remove")

    @discord.ui.button(label="Disable", style=discord.ButtonStyle.secondary)
    async def disable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "disable")

    @discord.ui.button(label="Enable", style=discord.ButtonStyle.secondary)
    async def enable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "enable")

    async def _open_action_modal(self, interaction: discord.Interaction, action: str) -> None:
        replies = list(await self._data_provider.list_replies(self._discord_channel_id))
        replies.extend(await self._data_provider.list_channel_event_replies(self._discord_channel_id))
        if not replies:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title="No Auto-Replies",
                    message="There are no auto-replies yet.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(
            ReplyActionModal(
                title=f"{action.capitalize()} Auto-Reply",
                event_bus=self._event_bus,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action=action,
                replies=replies,
                bound_message=self.bound_message,
            )
        )
