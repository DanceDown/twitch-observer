from __future__ import annotations

"""Centralized Discord embed styling helpers."""

import re

import discord

from src.database.connection import ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from src.events.event_types import DiscordCommandResult, DiscordResultStyle, TwitchChatMessageEvent


EMBED_COLORS: dict[DiscordResultStyle, int] = {
    DiscordResultStyle.SUCCESS: 0x2ECC71,
    DiscordResultStyle.ERROR: 0xE74C3C,
    DiscordResultStyle.INFO: 0x3498DB,
}


def build_result_embed(result: DiscordCommandResult) -> discord.Embed:
    """Render a command result into a consistently styled Discord embed."""
    return discord.Embed(
        title=result.title,
        description=result.message,
        color=EMBED_COLORS[result.style],
    )


def build_tracking_embed(
    *,
    event: TwitchChatMessageEvent,
    pattern: PatternRecord,
    thread: ThreadRecord,
    channel: ChannelRecord | None,
    reply: ReplyRecord | None = None,
    author_icon_url: str | None = None,
    channel_display_name: str | None = None,
) -> discord.Embed:
    """Render one matched Twitch message as a Discord embed."""
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
        text=f"Channel: {escape_discord_text(channel_display_name or event.channel_login)}",
    )
    if reply is not None:
        embed.add_field(name="Reply", value=escape_discord_preserving_links(reply.reply_message), inline=False)
    return embed


def build_auto_reply_embed(
    *,
    event: TwitchChatMessageEvent,
    pattern: PatternRecord,
    thread: ThreadRecord,
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
        channel=channel,
        reply=reply,
        author_icon_url=author_icon_url,
        channel_display_name=channel_display_name,
    )


def build_tracking_view(*, channel_login: str) -> discord.ui.View:
    """Build a compact URL-button view linking to the Twitch channel."""
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Open Channel", style=discord.ButtonStyle.link, url=f"https://www.twitch.tv/{channel_login}"))
    return view


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


def escape_discord_text(text: str) -> str:
    """Escape Discord markdown and mentions for display-only text fragments."""
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text))


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
