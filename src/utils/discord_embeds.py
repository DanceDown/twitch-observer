"""Centralized Discord embed styling helpers."""

from __future__ import annotations

import re

import discord

from src.database.connection import ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from src.events.event_types import DiscordCommandResult, DiscordResultStyle, TwitchChatMessageEvent
from src.localization import Localizer

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
        color=EMBED_COLORS[result.style],
    )
    if result.thumbnail_url:
        embed.set_thumbnail(url=result.thumbnail_url)
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
            CHANNEL=escape_discord_text(channel_display_name or event.channel_login),
            MESSAGE_ID=escape_discord_text(event.message_id or ""),
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


def _parse_hex_color(value: str) -> int:
    normalized = value.strip().lstrip("#")
    return int(normalized, 16)


_URL_PATTERN = re.compile(r"https?://[^\s]+")
_DISCORD_MARKDOWN_PATTERN = re.compile(r"([\\*_`~|>\[\]()])")
_DISCORD_MENTION_PATTERN = re.compile(r"@(everyone|here|[!&]?\d{15,20})")


def escape_discord_text(text: str) -> str:
    """Escape Discord markdown and mentions for display-only text fragments."""
    escaped_markdown = _DISCORD_MARKDOWN_PATTERN.sub(r"\\\1", text)
    return _DISCORD_MENTION_PATTERN.sub(lambda match: f"@\u200b{match.group(1)}", escaped_markdown)


def escape_discord_preserving_links(text: str) -> str:
    """Escape Discord formatting while keeping raw URLs clickable."""
    rendered = []
    last_end = 0
    for match in _URL_PATTERN.finditer(text):
        start, end = match.span()
        rendered.append(escape_discord_text(text[last_end:start]))
        rendered.append(match.group(0))
        last_end = end
    rendered.append(escape_discord_text(text[last_end:]))
    return "".join(rendered)


def format_twitch_code_link(*, display_name: str, login: str) -> str:
    """Render a Twitch profile link whose visible name is safe from markdown."""
    safe_name = display_name.replace("`", "")
    return f"[`{safe_name}`](https://www.twitch.tv/{login})"

