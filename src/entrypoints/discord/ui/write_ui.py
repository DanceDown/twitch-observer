"""Discord UI for `/write`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

import discord

from src.events.commands import SendTwitchMessageCommand
from src.localization import Localizer
from src.services.discord_ui_queries import TrackedChannelPresentation, WriteReplyCandidatePresentation

from ..dispatch import dispatch_send_twitch_message
from ..helpers import defer_interaction_response, send_initial_result
from .selects import window_with_included_items
from .shared import DiscordModalContext

_NO_REPLY_VALUE = "__none__"
DISCORD_SELECT_MAX_OPTIONS = 25


@dataclass(slots=True, frozen=True)
class WriteReplyOption:
    """Select-option data for one recent Twitch message reply target."""

    message_id: str
    twitch_channel_id: str
    label: str
    description: str


@dataclass(slots=True, frozen=True)
class WriteModalDefaults:
    """Optional field defaults used when `/write` opens as a modal."""

    channel_login: str | None = None
    message: str | None = None
    reply_parent_message_id: str | None = None


class WriteModal(discord.ui.Modal):
    """Send one manual Twitch message from inside Discord."""

    def __init__(
        self,
        *,
        context: DiscordModalContext,
        tracked_channels: list[TrackedChannelPresentation],
        reply_candidates: list[WriteReplyCandidatePresentation],
        defaults: WriteModalDefaults | None = None,
    ) -> None:
        """Create the modal for composing a manual Twitch chat message."""
        defaults = defaults or WriteModalDefaults()
        super().__init__(title=context.localizer.text("discord.write_ui.modal.title", language=context.language), timeout=300)
        self._context = context
        self._reply_map: dict[str, WriteReplyOption] = {}

        self.message = discord.ui.TextInput(
            label=context.localizer.text("discord.write_ui.modal.message_label", language=context.language),
            style=discord.TextStyle.paragraph,
            default=defaults.message,
            placeholder=context.localizer.text("discord.write_ui.modal.message_placeholder", language=context.language),
            required=True,
            max_length=500,
        )
        visible_channels = window_with_included_items(
            tracked_channels,
            key=lambda channel: channel.login,
            included_keys=[defaults.channel_login] if defaults.channel_login else [],
        )
        self.channel = discord.ui.Label(
            text=context.localizer.text("discord.write_ui.modal.channel_label", language=context.language),
            description=context.localizer.text("discord.write_ui.modal.channel_description", language=context.language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=channel.display_name[:100],
                        value=channel.login,
                        description=channel.login[:100],
                        default=channel.login == defaults.channel_login,
                    )
                    for channel in visible_channels
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.reply_target = discord.ui.Label(
            text=context.localizer.text("discord.write_ui.modal.reply_to_label", language=context.language),
            description=context.localizer.text("discord.write_ui.modal.reply_to_description", language=context.language),
            component=discord.ui.Select(
                options=self._build_reply_options(
                    reply_candidates,
                    localizer=context.localizer,
                    language=context.language,
                    default_reply_parent_message_id=defaults.reply_parent_message_id,
                ),
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.message)
        self.add_item(self.channel)
        self.add_item(self.reply_target)

    def _build_reply_options(
        self,
        candidates: list[WriteReplyCandidatePresentation],
        *,
        localizer: Localizer,
        language: str,
        default_reply_parent_message_id: str | None,
    ) -> list[discord.SelectOption]:
        options: list[discord.SelectOption] = [
            discord.SelectOption(
                label=localizer.text("discord.write_ui.modal.reply_to_none_label", language=language)[:100],
                value=_NO_REPLY_VALUE,
                description=localizer.text("discord.write_ui.modal.reply_to_none_description", language=language)[:100],
                default=default_reply_parent_message_id is None,
            )
        ]
        visible_candidates = window_with_included_items(
            candidates,
            key=lambda candidate: candidate.message_id,
            included_keys=[default_reply_parent_message_id] if default_reply_parent_message_id else [],
            limit=DISCORD_SELECT_MAX_OPTIONS - 1,
        )
        for candidate in visible_candidates:
            key = candidate.message_id
            if key in self._reply_map:
                continue
            label = f"{candidate.username}: {candidate.content}".strip()
            label = " ".join(label.split())
            if not label:
                label = candidate.username
            timestamp = candidate.timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
            description = f"{timestamp} - {candidate.twitch_channel_id}"
            self._reply_map[key] = WriteReplyOption(
                message_id=candidate.message_id,
                twitch_channel_id=candidate.twitch_channel_id,
                label=label,
                description=description,
            )
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=key,
                    description=description[:100],
                    default=key == default_reply_parent_message_id,
                )
            )
            if len(options) >= DISCORD_SELECT_MAX_OPTIONS:
                break
        return options

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch one manual Twitch send request."""
        await defer_interaction_response(interaction, ephemeral=True)
        selected_reply = self.reply_target.component.values[0]
        reply_parent_message_id = None if selected_reply == _NO_REPLY_VALUE else selected_reply
        result = await dispatch_send_twitch_message(
            self._context.services,
            SendTwitchMessageCommand(
                discord_channel_id=self._context.discord_channel_id,
                requester_id=self._context.requester_id,
                twitch_channel_login=self.channel.component.values[0],
                message=self.message.value.strip(),
                reply_parent_message_id=reply_parent_message_id,
            ),
        )
        await send_initial_result(interaction, result)
