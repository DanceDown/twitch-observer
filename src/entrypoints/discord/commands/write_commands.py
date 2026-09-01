"""Slash-command registration for manual Twitch writing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import discord

from src.discord_results import build_result
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import SendTwitchMessageCommand
from src.events.discord_results import DiscordResultStyle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.services.discord_ui_queries import WriteReplyCandidatePresentation

from ..dispatch import dispatch_send_twitch_message
from ..helpers import command_unavailable_result, ensure_ui_flow_allowed, send_initial_result
from ..ui.shared import DiscordModalContext, resolve_context_language
from ..ui.write_ui import WriteModal, WriteModalDefaults
from ..ui_data import TrackedChannelPresentation
from .localized import command_descriptions, command_text


class WriteCommandDataProvider(Protocol):
    """Read-side data needed by `/write` before opening its modal."""

    async def get_thread_language(self, discord_channel_id: int) -> str | None:
        """Return the configured language for a Discord context."""
        ...

    async def list_tracked_channels(self, discord_channel_id: int) -> list[TrackedChannelPresentation]:
        """Return tracked Twitch channels for the context."""
        ...

    async def list_recent_write_reply_candidates(
        self,
        *,
        discord_channel_id: int,
        max_age_minutes: int,
        limit: int,
    ) -> list[WriteReplyCandidatePresentation]:
        """Return recent Twitch messages available as reply parents."""
        ...

    async def get_write_reply_candidate(
        self,
        *,
        discord_channel_id: int,
        message_id: str,
    ) -> WriteReplyCandidatePresentation | None:
        """Return one Twitch message candidate by message ID."""
        ...


@dataclass(slots=True, frozen=True)
class WriteCommandOptions:
    """Configuration for the optional `/write` reply picker."""

    reply_candidate_max_age_minutes: int
    reply_candidate_limit: int


def register_write_commands(
    tree: discord.app_commands.CommandTree,
    services: DiscordServiceBundle,
    ui_data_provider: WriteCommandDataProvider,
    localizer: Localizer,
    options: WriteCommandOptions,
) -> None:
    """Register the single-word `/write` command."""

    @discord.app_commands.describe(
        **command_descriptions(
            localizer,
            twitch_channel_login="write.options.twitch_channel_login",
            message="write.options.message",
            reply_parent_message_id="write.options.reply_parent_message_id",
        )
    )
    @tree.command(name="write", description=command_text(localizer, "write.description"))
    async def write(
        interaction: discord.Interaction,
        twitch_channel_login: str | None = None,
        message: str | None = None,
        reply_parent_message_id: str | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return
        if not await ensure_ui_flow_allowed(interaction, services, flow=UIFlowKind.WRITE, step=UIFlowStep.ROOT):
            return

        normalized_login = (twitch_channel_login or "").strip()
        normalized_message = (message or "").strip()
        normalized_reply_parent_message_id = (reply_parent_message_id or "").strip() or None
        if normalized_login and normalized_message:
            result = await dispatch_send_twitch_message(
                services,
                SendTwitchMessageCommand(
                    discord_channel_id=interaction.channel_id,
                    requester_id=interaction.user.id,
                    twitch_channel_login=normalized_login,
                    message=normalized_message,
                    reply_parent_message_id=normalized_reply_parent_message_id,
                ),
            )
            await send_initial_result(interaction, result)
            return

        language = await resolve_context_language(
            localizer=localizer,
            data_provider=ui_data_provider,
            discord_channel_id=interaction.channel_id,
        )
        tracked_channels = await ui_data_provider.list_tracked_channels(interaction.channel_id)
        if not tracked_channels:
            await send_initial_result(
                interaction,
                build_result(
                    localizer,
                    "discord.write_ui.errors.no_channels",
                    language=language,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        recent_replies = await ui_data_provider.list_recent_write_reply_candidates(
            discord_channel_id=interaction.channel_id,
            max_age_minutes=options.reply_candidate_max_age_minutes,
            limit=max(options.reply_candidate_limit, 25),
        )
        if normalized_reply_parent_message_id and all(
            candidate.message_id != normalized_reply_parent_message_id for candidate in recent_replies
        ):
            selected_reply = await ui_data_provider.get_write_reply_candidate(
                discord_channel_id=interaction.channel_id,
                message_id=normalized_reply_parent_message_id,
            )
            if selected_reply is not None:
                recent_replies.append(selected_reply)
        await interaction.response.send_modal(
            WriteModal(
                context=DiscordModalContext(
                    services=services,
                    discord_channel_id=interaction.channel_id,
                    requester_id=interaction.user.id,
                    localizer=localizer,
                    language=language,
                ),
                tracked_channels=tracked_channels,
                reply_candidates=recent_replies,
                defaults=WriteModalDefaults(
                    channel_login=normalized_login or None,
                    message=normalized_message or None,
                    reply_parent_message_id=normalized_reply_parent_message_id,
                ),
            )
        )
