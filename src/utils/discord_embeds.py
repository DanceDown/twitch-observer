"""Centralized Discord embed styling helpers."""

from __future__ import annotations

from dataclasses import dataclass

import discord

from src.database.connection import ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from src.database.records import SupportTicketRecord
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.twitch_events import TwitchChatMessageEvent
from src.localization import LocalizationError, Localizer
from src.utils.discord_text import escape_discord_preserving_links

EMBED_COLORS: dict[DiscordResultStyle, int] = {
    DiscordResultStyle.SUCCESS: 0x2ECC71,
    DiscordResultStyle.ERROR: 0xE74C3C,
    DiscordResultStyle.INFO: 0x3498DB,
}
SUPPORT_CATEGORY_COLORS: dict[str, int] = {
    "bug": 0xE74C3C,
    "question": 0x3498DB,
    "idea": 0x2ECC71,
    "other": 0x808080,
}


@dataclass(slots=True, frozen=True)
class TrackingEmbedRequest:
    """Inputs for one Twitch-chat tracking embed."""

    event: TwitchChatMessageEvent
    pattern: PatternRecord
    thread: ThreadRecord
    localizer: Localizer
    channel: ChannelRecord | None
    reply: ReplyRecord | None = None
    author_icon_url: str | None = None
    channel_display_name: str | None = None


@dataclass(slots=True, frozen=True)
class ChannelEventAutoReplyEmbedRequest:
    """Inputs for one live/offline auto-reply tracking embed."""

    thread: ThreadRecord
    localizer: Localizer
    channel_display_name: str
    channel_login: str | None
    state: str
    reply_message: str
    channel: ChannelRecord | None
    event_color: str | None
    twitch_chat_color: str | None = None
    channel_icon_url: str | None = None


@dataclass(slots=True, frozen=True)
class SupportUserAnswerEmbedRequest:
    """Inputs for the answer sent back to the ticket requester."""

    ticket: SupportTicketRecord
    localizer: Localizer
    response_subject: str
    response_body: str
    color: str | None = None


def build_result_embed(result: DiscordCommandResult) -> discord.Embed:
    """Render a command result into a consistently styled Discord embed."""
    embed = discord.Embed(
        title=result.title,
        description=result.message,
        color=_result_embed_color(result),
    )
    if result.thumbnail_url:
        embed.set_thumbnail(url=result.thumbnail_url)
    if result.author_name:
        embed.set_author(
            name=result.author_name,
            url=result.author_url,
            icon_url=result.author_icon_url,
        )
    if result.footer:
        embed.set_footer(text=result.footer)
    return embed


def build_tracking_embed(request: TrackingEmbedRequest) -> discord.Embed:
    """Render one matched Twitch message as a Discord embed."""
    language = request.localizer.language_for_thread(request.thread)
    embed = discord.Embed(
        title="",
        description=escape_discord_preserving_links(request.event.content),
        color=resolve_tracking_color(
            event=request.event,
            pattern=request.pattern,
            channel=request.channel,
            thread=request.thread,
        ),
    )
    embed.set_author(
        name=request.event.author_display_name or request.event.author_login,
        url=f"https://www.twitch.tv/{request.event.author_login}",
        icon_url=request.author_icon_url,
    )
    embed.set_footer(
        text=request.localizer.text(
            "discord.tracking_embed.footer_channel",
            language=language,
            sources={"view": {"channel_name": request.channel_display_name or request.event.channel_login}},
        ),
    )
    if request.reply is not None:
        embed.add_field(
            name=request.localizer.text("discord.tracking_embed.reply_field", language=language),
            value=escape_discord_preserving_links(request.reply.reply_message),
            inline=False,
        )
    return embed


def build_auto_reply_embed(request: TrackingEmbedRequest) -> discord.Embed:
    """Render one matched Twitch message that also triggered an auto-reply."""
    return build_tracking_embed(request)


def build_channel_event_auto_reply_embed(request: ChannelEventAutoReplyEmbedRequest) -> discord.Embed:
    """Render one live/offline ping auto-reply notification for Discord tracking."""
    language = request.localizer.language_for_thread(request.thread)
    description_key = (
        "discord.channel_event_reply_embed.description_online"
        if request.state == "online"
        else "discord.channel_event_reply_embed.description_offline"
    )
    embed = discord.Embed(
        title=request.localizer.text(
            "discord.channel_event_reply_embed.title",
            language=language,
        ),
        description=request.localizer.text(
            description_key,
            language=language,
            sources={
                "view": {
                    "channel": {
                        "display_name": request.channel_display_name,
                        "login": request.channel_login,
                    }
                }
            },
        ),
        color=resolve_channel_event_color(
            event_color=request.event_color,
            channel=request.channel,
            thread=request.thread,
            twitch_chat_color=request.twitch_chat_color,
        ),
    )
    embed.set_author(
        name=request.localizer.text(
            "discord.channel_event_reply_embed.author_name",
            language=language,
            sources={"view": {"channel": {"display_name": request.channel_display_name}}},
        ),
        url=None if not request.channel_login else f"https://www.twitch.tv/{request.channel_login}",
        icon_url=request.channel_icon_url,
    )
    if request.channel_icon_url:
        embed.set_thumbnail(url=request.channel_icon_url)
    embed.add_field(
        name=request.localizer.text("discord.channel_event_reply_embed.reply_field", language=language),
        value=escape_discord_preserving_links(request.reply_message),
        inline=False,
    )
    return embed


def build_support_ticket_embed(
    *,
    ticket: SupportTicketRecord,
    localizer: Localizer,
) -> discord.Embed:
    """Render an open support ticket for the configured support channel."""
    return _build_support_ticket_state_embed(
        ticket=ticket,
        localizer=localizer,
        key="discord.support.embed.ticket",
    )


def build_support_answered_ticket_embed(
    *,
    ticket: SupportTicketRecord,
    localizer: Localizer,
) -> discord.Embed:
    """Render an answered support ticket for the configured support channel."""
    return _build_support_ticket_state_embed(
        ticket=ticket,
        localizer=localizer,
        key="discord.support.embed.answered",
    )


def build_support_closed_ticket_embed(
    *,
    ticket: SupportTicketRecord,
    localizer: Localizer,
) -> discord.Embed:
    """Render a closed support ticket for the configured support channel."""
    return _build_support_ticket_state_embed(
        ticket=ticket,
        localizer=localizer,
        key="discord.support.embed.closed",
    )


def build_support_user_answer_embed(request: SupportUserAnswerEmbedRequest) -> discord.Embed:
    """Render the support answer that is sent into the requester's origin channel."""
    language = request.localizer.resolve_language(request.ticket.language)
    entry = request.localizer.value("discord.support.user_answer_embed", language=language)
    if not isinstance(entry, dict):
        raise LocalizationError.translation_key_not_object("discord.support.user_answer_embed")
    title = entry.get("title")
    body = entry.get("body")
    footer = entry.get("footer")
    placeholder_specs = entry.get("placeholders")
    if not isinstance(title, str) or not isinstance(body, str) or not isinstance(footer, str):
        raise LocalizationError.translation_result_missing_strings("discord.support.user_answer_embed")
    if placeholder_specs is not None and not isinstance(placeholder_specs, dict):
        raise LocalizationError.translation_result_invalid_placeholders("discord.support.user_answer_embed")

    sources = {
        "view": {
            **_support_ticket_view(request.ticket, localizer=request.localizer, language=language),
            "response_subject": request.response_subject,
            "response_body": request.response_body,
        }
    }
    embed = discord.Embed(
        title=request.localizer.render_with_placeholders(
            title,
            language=language,
            sources=sources,
            placeholder_specs=placeholder_specs,
        ),
        description=request.localizer.render_with_placeholders(
            body,
            language=language,
            sources=sources,
            placeholder_specs=placeholder_specs,
        ),
        color=_parse_hex_color(request.color) if request.color else EMBED_COLORS[DiscordResultStyle.SUCCESS],
    )
    if footer:
        embed.set_footer(
            text=request.localizer.render_with_placeholders(
                footer,
                language=language,
                sources=sources,
                placeholder_specs=placeholder_specs,
            )
        )
    return embed


def resolve_tracking_color(
    *,
    event: TwitchChatMessageEvent,
    pattern: PatternRecord,
    channel: ChannelRecord | None,
    thread: ThreadRecord,
) -> int:
    """Resolve the embed color for a matched Twitch message."""
    if pattern.color:
        return _parse_hex_color(pattern.color)
    if channel is not None and channel.color:
        return _parse_hex_color(channel.color)
    if thread.color:
        return _parse_hex_color(thread.color)
    if event.color:
        return _parse_hex_color(event.color)
    return 0x808080


def resolve_channel_event_color(
    *,
    event_color: str | None,
    channel: ChannelRecord | None,
    thread: ThreadRecord,
    twitch_chat_color: str | None,
) -> int:
    """Resolve the embed color for tracked live/offline ping notifications."""
    if event_color:
        return _parse_hex_color(event_color)
    if channel is not None and channel.color:
        return _parse_hex_color(channel.color)
    if thread.color:
        return _parse_hex_color(thread.color)
    if twitch_chat_color:
        return _parse_hex_color(twitch_chat_color)
    return 0x808080


def resolve_support_ticket_color(*, category: str) -> int:
    """Resolve the support-channel embed color for one ticket category."""
    return SUPPORT_CATEGORY_COLORS.get(category, SUPPORT_CATEGORY_COLORS["other"])


def _result_embed_color(result: DiscordCommandResult) -> int:
    if result.color:
        return _parse_hex_color(result.color)
    return EMBED_COLORS[result.style]


def _parse_hex_color(value: str) -> int:
    normalized = value.strip().lstrip("#")
    return int(normalized, 16)


def _build_support_ticket_state_embed(
    *,
    ticket: SupportTicketRecord,
    localizer: Localizer,
    key: str,
) -> discord.Embed:
    language = localizer.resolve_language(ticket.language)
    entry = localizer.value(key, language=language)
    if not isinstance(entry, dict):
        raise LocalizationError.translation_key_not_object(key)
    title = entry.get("title")
    body = entry.get("body")
    footer = entry.get("footer")
    placeholder_specs = entry.get("placeholders")
    if not isinstance(title, str) or not isinstance(body, str) or not isinstance(footer, str):
        raise LocalizationError.translation_result_missing_strings(key)
    if placeholder_specs is not None and not isinstance(placeholder_specs, dict):
        raise LocalizationError.translation_result_invalid_placeholders(key)

    sources = {"view": _support_ticket_view(ticket, localizer=localizer, language=language)}
    embed = discord.Embed(
        title=localizer.render_with_placeholders(
            title,
            language=language,
            sources=sources,
            placeholder_specs=placeholder_specs,
        ),
        description=localizer.render_with_placeholders(
            body,
            language=language,
            sources=sources,
            placeholder_specs=placeholder_specs,
        ),
        color=resolve_support_ticket_color(category=ticket.category),
    )
    if footer:
        embed.set_footer(
            text=localizer.render_with_placeholders(
                footer,
                language=language,
                sources=sources,
                placeholder_specs=placeholder_specs,
            )
        )
    return embed


def _support_ticket_view(ticket: SupportTicketRecord, *, localizer: Localizer, language: str) -> dict[str, object]:
    return {
        "ticket_id": ticket.ticket_id,
        "source_channel_id": ticket.source_discord_channel_id,
        "requester_id": ticket.requester_discord_user_id,
        "category": ticket.category,
        "category_label": localizer.lookup("discord.support.category", ticket.category, language=language),
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status,
        "status_label": localizer.lookup("discord.support.status", ticket.status, language=language),
        "support_message_id": ticket.support_message_id or "",
        "response_subject": ticket.response_subject or "",
        "response_body": ticket.response_body or "",
        "responded_by": ticket.responded_by_discord_user_id or "",
        "responded_at": ticket.responded_at,
        "closed_by": ticket.closed_by_discord_user_id or "",
        "closed_at": ticket.closed_at,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
    }
