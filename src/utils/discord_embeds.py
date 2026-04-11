from __future__ import annotations

"""Centralized Discord embed styling helpers."""

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
) -> discord.Embed:
    """Render one matched Twitch message as a Discord embed."""
    embed = discord.Embed(
        title=event.author_display_name or event.author_login,
        description=event.content,
        color=resolve_tracking_color(event=event, pattern=pattern, channel=channel, thread=thread),
    )
    embed.add_field(name="Channel", value=f"`{event.channel_login}`", inline=True)
    embed.add_field(name="Match", value=f"`{pattern.regex}`", inline=True)
    embed.add_field(name="Mode", value="Regex" if pattern.is_regex else "Ping", inline=True)
    if reply is not None:
        embed.add_field(name="Auto Reply", value=f"`{reply.reply_message}`", inline=False)
        embed.add_field(name="Reply Mode", value="Reply" if reply.reply_as_reply else "Message", inline=True)
    return embed


def build_auto_reply_embed(
    *,
    event: TwitchChatMessageEvent,
    pattern: PatternRecord,
    thread: ThreadRecord,
    reply: ReplyRecord,
    channel: ChannelRecord | None = None,
) -> discord.Embed:
    """Render one matched Twitch message that also triggered an auto-reply."""
    embed = build_tracking_embed(event=event, pattern=pattern, thread=thread, channel=channel, reply=reply)
    embed.add_field(name="Status", value="Auto-replied", inline=True)
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


def _parse_hex_color(value: str) -> int:
    normalized = value.strip().lstrip("#")
    return int(normalized, 16)
