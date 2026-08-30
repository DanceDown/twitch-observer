"""Discord UI components for support tickets."""

from __future__ import annotations

from contextlib import suppress
import logging
from typing import cast

import discord

from src.entrypoints.discord.delivery import send_embed_with_retries, send_embed_message_with_retries
from src.entrypoints.discord.helpers import defer_interaction_response, send_initial_result, send_modal_response
from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.discord_results import DiscordResultStyle
from src.localization import Localizer
from src.services.support_command_service import (
    SUPPORT_RESPONSE_BODY_MAX_LENGTH,
    SUPPORT_RESPONSE_SUBJECT_MAX_LENGTH,
    SupportTicketCreateResult,
    SupportTicketMessageResult,
    SupportTicketUpdateResult,
)
from src.utils.discord_embeds import (
    build_result_embed,
    build_support_answered_ticket_embed,
    build_support_closed_ticket_embed,
    build_support_ticket_embed,
)

from ..dispatch import (
    dispatch_mark_support_answered,
    dispatch_mark_support_closed,
    dispatch_prepare_support_answer,
    dispatch_prepare_support_close,
    dispatch_show_support_ticket_configuration,
)
from .show_ui import ShowPaginationView, _show_section_item_prefix

logger = logging.getLogger(__name__)


class SupportTicketView(discord.ui.View):
    """Persistent action view attached to open support tickets."""

    def __init__(
        self,
        *,
        ticket_id: int,
        services: DiscordServiceBundle,
        localizer: Localizer,
        language: str,
    ) -> None:
        super().__init__(timeout=None)
        self._ticket_id = ticket_id
        self._services = services
        self._localizer = localizer
        self._language = localizer.resolve_language(language)
        self.reply.label = localizer.text("discord.support.actions.reply", language=self._language)
        self.reply.custom_id = _support_action_custom_id("reply", ticket_id)
        self.close.label = localizer.text("discord.support.actions.close", language=self._language)
        self.close.custom_id = _support_action_custom_id("close", ticket_id)
        self.show.label = localizer.text("discord.support.actions.show", language=self._language)
        self.show.custom_id = _support_action_custom_id("show", ticket_id)

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def reply(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Open the reply modal for one open ticket."""
        if not await self._ensure_support_channel(interaction):
            return
        ticket_result = await self._services.support.get_open_ticket_result(
            ticket_id=self._ticket_id,
            language_hint=self._language,
        )
        if ticket_result.ticket is None:
            await send_initial_result(interaction, ticket_result.result)
            return
        await send_modal_response(
            interaction,
            SupportReplyModal(
                ticket_id=self._ticket_id,
                services=self._services,
                localizer=self._localizer,
                language=ticket_result.ticket.language,
                support_message=_interaction_message(interaction),
            ),
        )

    @discord.ui.button(label="_", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Close one open ticket and notify the requesting channel."""
        if not await self._ensure_support_channel(interaction):
            return
        await defer_interaction_response(interaction, ephemeral=True)
        prepared = cast(
            SupportTicketMessageResult,
            await dispatch_prepare_support_close(
                self._services,
                ticket_id=self._ticket_id,
                closer_id=interaction.user.id,
            ),
        )
        if prepared.ticket is None:
            await send_initial_result(interaction, prepared.result)
            return
        if not await _send_to_origin_channel(
            interaction.client,
            channel_id=prepared.ticket.source_discord_channel_id,
            embed=build_result_embed(prepared.result),
            purpose="support close user notice",
        ):
            await send_initial_result(interaction, self._services.support.delivery_failed_result(prepared.ticket))
            return

        updated = cast(
            SupportTicketUpdateResult,
            await dispatch_mark_support_closed(
                self._services,
                ticket_id=self._ticket_id,
                closer_id=interaction.user.id,
            ),
        )
        if updated.ticket is None:
            await send_initial_result(interaction, updated.result)
            return
        await _edit_support_message(
            _interaction_message(interaction),
            embed=build_support_closed_ticket_embed(ticket=updated.ticket, localizer=self._localizer),
        )
        await send_initial_result(interaction, updated.result)

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def show(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Open the support-owned show section picker for the ticket origin."""
        if not await self._ensure_support_channel(interaction):
            return
        await send_modal_response(
            interaction,
            SupportShowSectionModal(
                ticket_id=self._ticket_id,
                requester_id=interaction.user.id,
                services=self._services,
                localizer=self._localizer,
                language=self._language,
            ),
        )

    async def _ensure_support_channel(self, interaction: discord.Interaction) -> bool:
        if self._services.support.is_support_channel(interaction.channel_id):
            return True
        await send_initial_result(
            interaction,
            self._services.support.wrong_channel_result(language_hint=self._language),
        )
        return False


class SupportReplyModal(discord.ui.Modal):
    """Collect the supporter's subject and Markdown-capable answer."""

    def __init__(
        self,
        *,
        ticket_id: int,
        services: DiscordServiceBundle,
        localizer: Localizer,
        language: str,
        support_message: discord.Message | discord.InteractionMessage | None,
    ) -> None:
        resolved_language = localizer.resolve_language(language)
        super().__init__(title=localizer.text("discord.support.reply_modal.title", language=resolved_language), timeout=300)
        self._ticket_id = ticket_id
        self._services = services
        self._localizer = localizer
        self._language = resolved_language
        self._support_message = support_message
        self.subject = discord.ui.TextInput(
            label=localizer.text("discord.support.reply_modal.subject_label", language=resolved_language),
            placeholder=localizer.text("discord.support.reply_modal.subject_placeholder", language=resolved_language),
            required=True,
            max_length=SUPPORT_RESPONSE_SUBJECT_MAX_LENGTH,
        )
        self.body = discord.ui.TextInput(
            label=localizer.text("discord.support.reply_modal.body_label", language=resolved_language),
            placeholder=localizer.text("discord.support.reply_modal.body_placeholder", language=resolved_language),
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=SUPPORT_RESPONSE_BODY_MAX_LENGTH,
        )
        self.add_item(self.subject)
        self.add_item(self.body)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Send an answer to the requester and mark the ticket answered."""
        await defer_interaction_response(interaction, ephemeral=True)
        prepared = cast(
            SupportTicketMessageResult,
            await dispatch_prepare_support_answer(
                self._services,
                ticket_id=self._ticket_id,
                responder_id=interaction.user.id,
                subject=str(self.subject.value),
                body=str(self.body.value),
            ),
        )
        if prepared.ticket is None:
            await send_initial_result(interaction, prepared.result)
            return
        if not await _send_to_origin_channel(
            interaction.client,
            channel_id=prepared.ticket.source_discord_channel_id,
            embed=build_result_embed(prepared.result),
            purpose="support answer user notice",
        ):
            await send_initial_result(interaction, self._services.support.delivery_failed_result(prepared.ticket))
            return

        updated = cast(
            SupportTicketUpdateResult,
            await dispatch_mark_support_answered(
                self._services,
                ticket_id=self._ticket_id,
                responder_id=interaction.user.id,
                subject=str(self.subject.value),
                body=str(self.body.value),
            ),
        )
        if updated.ticket is None:
            await send_initial_result(interaction, updated.result)
            return
        await _edit_support_message(
            self._support_message,
            embed=build_support_answered_ticket_embed(ticket=updated.ticket, localizer=self._localizer),
        )
        await send_initial_result(interaction, updated.result)


class SupportShowSectionModal(discord.ui.Modal):
    """Collect the `/show` section a supporter wants to inspect."""

    def __init__(
        self,
        *,
        ticket_id: int,
        requester_id: int,
        services: DiscordServiceBundle,
        localizer: Localizer,
        language: str,
    ) -> None:
        resolved_language = localizer.resolve_language(language)
        super().__init__(title=localizer.text("discord.support.show_modal.title", language=resolved_language), timeout=300)
        self._ticket_id = ticket_id
        self._requester_id = requester_id
        self._services = services
        self._localizer = localizer
        self._language = resolved_language
        self.section = discord.ui.Label(
            text=localizer.text("discord.support.show_modal.section_label", language=resolved_language),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=localizer.text("discord.support.show_modal.section_option.pings", language=resolved_language),
                        value="pings",
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text(
                            "discord.support.show_modal.section_option.auto_replies",
                            language=resolved_language,
                        ),
                        value="auto_replies",
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text(
                            "discord.support.show_modal.section_option.stream_pings",
                            language=resolved_language,
                        ),
                        value="stream_pings",
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text("discord.support.show_modal.section_option.channels", language=resolved_language),
                        value="channels",
                        default=True,
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text("discord.support.show_modal.section_option.users", language=resolved_language),
                        value="users",
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text(
                            "discord.support.show_modal.section_option.permissions",
                            language=resolved_language,
                        ),
                        value="permissions",
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text("discord.support.show_modal.section_option.account", language=resolved_language),
                        value="account",
                    ),
                ]
            ),
        )
        self.add_item(self.section)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Render the selected ticket-origin configuration."""
        result = await dispatch_show_support_ticket_configuration(
            self._services,
            ticket_id=self._ticket_id,
            requester_id=self._requester_id,
            sections=(self.section.component.value or "channels",),
        )
        if result.style != DiscordResultStyle.INFO or not result.ephemeral:
            await send_initial_result(interaction, result)
            return

        section = self.section.component.value or "channels"
        view = ShowPaginationView(
            owner_id=self._requester_id,
            result=result,
            localizer=self._localizer,
            language=result.language or self._language,
            item_prefix=_show_section_item_prefix(
                localizer=self._localizer,
                language=result.language or self._language,
                section=section,
            ),
        )
        await interaction.response.send_message(embed=view.render_embed(), view=view, ephemeral=True)
        view.bound_message = await interaction.original_response()


async def send_new_support_ticket(
    *,
    client: discord.Client,
    creation: SupportTicketCreateResult,
    services: DiscordServiceBundle,
    localizer: Localizer,
) -> bool:
    """Send a freshly created ticket to the configured support channel."""
    if creation.ticket is None or creation.support_discord_channel_id is None:
        return False
    support_channel = await _resolve_messageable_channel(client, creation.support_discord_channel_id)
    if support_channel is None:
        return False
    view = SupportTicketView(
        ticket_id=creation.ticket.ticket_id,
        services=services,
        localizer=localizer,
        language=creation.ticket.language,
    )
    message = await send_embed_message_with_retries(
        support_channel,
        embed=build_support_ticket_embed(ticket=creation.ticket, localizer=localizer),
        view=view,
        allowed_mentions=_support_allowed_mentions(),
        purpose="support ticket",
    )
    if message is None:
        return False
    try:
        await services.support.record_support_message(ticket_id=creation.ticket.ticket_id, support_message_id=message.id)
    except Exception:
        logger.warning("Could not record support message ID for ticket_id=%s.", creation.ticket.ticket_id, exc_info=True)
    return True


async def register_persistent_support_views(
    *,
    client: discord.Client,
    services: DiscordServiceBundle,
    localizer: Localizer,
) -> None:
    """Restore persistent support-ticket buttons for open tickets after startup."""
    try:
        tickets = await services.support.list_open_tickets_with_messages()
    except Exception:
        logger.warning("Could not restore persistent support ticket views.", exc_info=True)
        return

    for ticket in tickets:
        if ticket.support_message_id is None:
            continue
        client.add_view(
            SupportTicketView(
                ticket_id=ticket.ticket_id,
                services=services,
                localizer=localizer,
                language=ticket.language,
            ),
            message_id=ticket.support_message_id,
        )
    if tickets:
        logger.info("Restored %s persistent support ticket view(s).", len(tickets))


async def _send_to_origin_channel(
    client: discord.Client,
    *,
    channel_id: int,
    embed: discord.Embed,
    purpose: str,
) -> bool:
    channel = await _resolve_messageable_channel(client, channel_id)
    if channel is None:
        return False
    try:
        return await send_embed_with_retries(
            channel,
            embed=embed,
            allowed_mentions=_support_allowed_mentions(),
            purpose=purpose,
        )
    except (discord.Forbidden, discord.NotFound):
        return False


async def _resolve_messageable_channel(
    client: discord.Client,
    channel_id: int,
) -> discord.abc.Messageable | None:
    try:
        channel = client.get_channel(channel_id)
        if channel is None:
            channel = await client.fetch_channel(channel_id)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return None
    if isinstance(channel, discord.TextChannel | discord.Thread | discord.DMChannel):
        return channel
    if hasattr(channel, "send"):
        return cast(discord.abc.Messageable, channel)
    return None


async def _edit_support_message(
    message: discord.Message | discord.InteractionMessage | None,
    *,
    embed: discord.Embed,
) -> None:
    if message is None:
        return
    with suppress(discord.HTTPException, discord.Forbidden, discord.NotFound):
        await message.edit(embed=embed, view=None)


def _interaction_message(interaction: discord.Interaction) -> discord.Message | discord.InteractionMessage | None:
    return cast(discord.Message | discord.InteractionMessage | None, getattr(interaction, "message", None))


def _support_action_custom_id(action: str, ticket_id: int) -> str:
    return f"support:{action}:{ticket_id}"


def _support_allowed_mentions() -> discord.AllowedMentions:
    return discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)
