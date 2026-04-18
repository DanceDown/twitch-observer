from __future__ import annotations

"""Discord UI for `/reply`."""

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.utils.discord_embeds import build_result_embed

from ..dispatch import dispatch_reply_command
from ..helpers import complete_bound_result, normalize_optional_text, send_initial_result
from ..ui_data import DiscordUIDataProvider, PatternPresentation, ReplyPresentation
from .shared import BaseFormView, build_form_embed


def _pattern_label(pattern: PatternPresentation) -> str:
    """Build a compact human-readable label for one pattern option."""
    return (pattern.pattern.regex or "Untitled ping")[:100]


def _reply_label(reply: ReplyPresentation) -> str:
    """Build a compact human-readable label for one reply option."""
    return reply.reply.reply_message[:100]


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
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        self.pattern = discord.ui.Label(
            text="Ping",
            description="Choose the ping that should trigger this automatic reply.",
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_pattern_label(pattern),
                        value=str(pattern.pattern.p_index),
                        description=f"ID {pattern.pattern.p_index} - {'Regex' if pattern.pattern.is_regex else 'Ping'}",
                    )
                    for pattern in patterns[:25]
                ],
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
        result = await dispatch_reply_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action="add",
            pattern_id=int(self.pattern.component.values[0]),
            message=normalize_optional_text(self.message.value),
            reply_as_reply=self.mode.component.value == "reply",
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
        replies: list[ReplyPresentation],
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
                        value=str(reply.reply.p_index),
                        description=f"Linked to: {_pattern_label(reply.pattern)}",
                    )
                    for reply in replies[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.reply)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the selected reply action."""
        result = await dispatch_reply_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action=self._action,
            pattern_id=int(self.reply.component.values[0]),
            message=None,
            reply_as_reply=False,
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
            "Attach an automatic message to a ping, or disable/enable an auto-reply.",
        )

    @discord.ui.button(label="Add", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        patterns = await self._data_provider.list_patterns(self._discord_channel_id)
        if not patterns:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title="No Pings Yet",
                    message="Create a ping first before attaching an auto-reply.",
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
        replies = await self._data_provider.list_replies(self._discord_channel_id)
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
