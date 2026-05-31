"""Centralized Discord embed styling helpers."""

from __future__ import annotations

import discord

from src.database.connection import ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from src.events.event_types import DiscordCommandResult, DiscordResultStyle, TwitchChatMessageEvent
from src.localization import Localizer
from src.utils.discord_text import escape_discord_preserving_links, escape_discord_text

EMBED_COLORS: dict[DiscordResultStyle, int] = {
    DiscordResultStyle.SUCCESS: 0x2ECC71,
    DiscordResultStyle.ERROR: 0xE74C3C,
    DiscordResultStyle.INFO: 0x3498DB,
}


def build_result_embed(result: DiscordCommandResult) -> discord.Embed:
    """Render a command result into a consistently styled Discord embed."""
    embed = discord.Embed(
        title=result.title,
        description=result.message,
        color=_result_embed_color(result),
    )
    if result.thumbnail_url:
        embed.set_thumbnail(url=result.thumbnail_url)
    if result.footer:
        embed.set_footer(text=result.footer)
    return embed


def build_tracking_embed(
    *,
    event: TwitchChatMessageEvent,
    pattern: PatternRecord,
    thread: ThreadRecord,
    localizer: Localizer,
    channel: ChannelRecord | None,
    reply: ReplyRecord | None = None,
    author_icon_url: str | None = None,
    channel_display_name: str | None = None,
) -> discord.Embed:
    """Render one matched Twitch message as a Discord embed."""
    language = localizer.language_for_thread(thread)
    embed = discord.Embed(
        title="",
        description=escape_discord_preserving_links(event.content),
        color=resolve_tracking_color(event=event, pattern=pattern, channel=channel, thread=thread),
    )
    embed.set_author(
        name=escape_discord_text(event.author_display_name or event.author_login),
        url=f"https://www.twitch.tv/{event.author_login}",
        icon_url=author_icon_url,
    )
    embed.set_footer(
        text=localizer.text(
            "discord.tracking_embed.footer_channel",
            language=language,
            CHANNEL=(channel_display_name or event.channel_login),
        ),
    )
    if reply is not None:
        embed.add_field(
            name=localizer.text("discord.tracking_embed.reply_field", language=language),
            value=escape_discord_preserving_links(reply.reply_message),
            inline=False,
        )
    return embed


def build_auto_reply_embed(
    *,
    event: TwitchChatMessageEvent,
    pattern: PatternRecord,
    thread: ThreadRecord,
    localizer: Localizer,
    reply: ReplyRecord,
    channel: ChannelRecord | None = None,
    author_icon_url: str | None = None,
    channel_display_name: str | None = None,
) -> discord.Embed:
    """Render one matched Twitch message that also triggered an auto-reply."""
    return build_tracking_embed(
        event=event,
        pattern=pattern,
        thread=thread,
        localizer=localizer,
        channel=channel,
        reply=reply,
        author_icon_url=author_icon_url,
        channel_display_name=channel_display_name,
    )


def build_channel_event_auto_reply_embed(
    *,
    thread: ThreadRecord,
    localizer: Localizer,
    display_index: int,
    channel_display_name: str,
    channel_login: str | None,
    state: str,
    reply_message: str,
    channel: ChannelRecord | None,
    event_color: str | None,
    channel_icon_url: str | None = None,
) -> discord.Embed:
    """Render one live/offline ping auto-reply notification for Discord tracking."""
    language = localizer.language_for_thread(thread)
    embed = discord.Embed(
        title="",
        description=localizer.text(
            "discord.channel_event_reply_embed.description",
            language=language,
            ID=display_index,
            STATE=state,
        ),
        color=resolve_channel_event_color(
            event_color=event_color,
            channel=channel,
            thread=thread,
        ),
    )
    author_name = escape_discord_text(channel_display_name)
    if channel_login:
        embed.set_author(
            name=author_name,
            url=f"https://www.twitch.tv/{channel_login}",
            icon_url=channel_icon_url,
        )
    else:
        embed.set_author(name=author_name, icon_url=channel_icon_url)
    embed.set_footer(
        text=localizer.text(
            "discord.channel_event_reply_embed.footer",
            language=language,
            CHANNEL=channel_display_name,
        ),
    )
    embed.add_field(
        name=localizer.text("discord.channel_event_reply_embed.reply_field", language=language),
        value=escape_discord_preserving_links(reply_message),
        inline=False,
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
) -> int:
    """Resolve the embed color for tracked live/offline ping notifications."""
    if event_color:
        return _parse_hex_color(event_color)
    if channel is not None and channel.color:
        return _parse_hex_color(channel.color)
    if thread.color:
        return _parse_hex_color(thread.color)
    return 0x808080


def _result_embed_color(result: DiscordCommandResult) -> int:
    if result.color:
        return _parse_hex_color(result.color)
    return EMBED_COLORS[result.style]


def _parse_hex_color(value: str) -> int:
    normalized = value.strip().lstrip("#")
    return int(normalized, 16)
