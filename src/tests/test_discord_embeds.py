from __future__ import annotations

from datetime import datetime, timezone

import discord

from src.database.connection import ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from src.events.event_types import DiscordCommandResult, DiscordResultStyle, TwitchChatMessageEvent
from src.utils.discord_embeds import EMBED_COLORS, build_auto_reply_embed, build_result_embed, build_tracking_embed, build_tracking_view


def _build_event(*, color: str | None) -> TwitchChatMessageEvent:
    return TwitchChatMessageEvent(
        channel_login="example",
        author_login="alice",
        author_display_name="Alice",
        author_id="7",
        broadcaster_id="42",
        message_id="msg-1",
        content="hello there",
        color=color,
        sent_at=datetime.now(timezone.utc),
        raw_tags={"badges": ""},
    )


def _build_thread(*, color: str | None) -> ThreadRecord:
    return ThreadRecord(
        thread_id=1,
        owner_id=200,
        discord_channel_id=100,
        enabled=True,
        color=color,
    )


def _build_pattern(*, color: str | None) -> PatternRecord:
    return PatternRecord(
        thread_id=1,
        p_index=1,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=color,
        disabled=False,
        notify=True,
        priority=0,
    )


def test_build_result_embed_uses_centralized_color_palette() -> None:
    result = DiscordCommandResult(
        title="Channel Added",
        message="Added Twitch channel `example`.",
        style=DiscordResultStyle.SUCCESS,
    )

    embed = build_result_embed(result)

    assert embed.title == "Channel Added"
    assert embed.description == "Added Twitch channel `example`."
    assert embed.color.value == EMBED_COLORS[DiscordResultStyle.SUCCESS]


def test_tracking_embed_prefers_pattern_color_over_all_fallbacks() -> None:
    embed = build_tracking_embed(
        event=_build_event(color="#abcdef"),
        pattern=_build_pattern(color="#123456"),
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color="#654321"),
        thread=_build_thread(color="#111111"),
    )

    assert embed.color.value == 0x123456


def test_tracking_embed_uses_channel_color_when_pattern_color_is_missing() -> None:
    embed = build_tracking_embed(
        event=_build_event(color="#abcdef"),
        pattern=_build_pattern(color=None),
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color="#654321"),
        thread=_build_thread(color="#111111"),
    )

    assert embed.color.value == 0x654321


def test_tracking_embed_uses_thread_color_when_pattern_and_channel_color_are_missing() -> None:
    embed = build_tracking_embed(
        event=_build_event(color="#abcdef"),
        pattern=_build_pattern(color=None),
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color=None),
        thread=_build_thread(color="#111111"),
    )

    assert embed.color.value == 0x111111


def test_tracking_embed_uses_twitch_user_color_before_gray_fallback() -> None:
    embed = build_tracking_embed(
        event=_build_event(color="#abcdef"),
        pattern=_build_pattern(color=None),
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color=None),
        thread=_build_thread(color=None),
    )

    assert embed.color.value == 0xABCDEF


def test_tracking_embed_uses_gray_when_no_color_source_exists() -> None:
    embed = build_tracking_embed(
        event=_build_event(color=None),
        pattern=_build_pattern(color=None),
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color=None),
        thread=_build_thread(color=None),
    )

    assert embed.color.value == 0x808080


def test_auto_reply_embed_mentions_sent_reply_message() -> None:
    embed = build_auto_reply_embed(
        event=_build_event(color=None),
        pattern=_build_pattern(color="#123456"),
        thread=_build_thread(color=None),
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color=None),
        reply=ReplyRecord(
            thread_id=1,
            p_index=1,
            reply_message="Hi Alice",
            reply_as_reply=True,
            disabled=False,
        ),
    )

    assert embed.title == ""
    field_names = [field.name for field in embed.fields]
    assert "Reply" in field_names
    assert embed.color.value == 0x123456


def test_tracking_embed_escapes_markdown_but_keeps_links_clickable() -> None:
    event = TwitchChatMessageEvent(
        channel_login="example",
        author_login="alice",
        author_display_name="Alice",
        author_id="7",
        broadcaster_id="42",
        message_id="msg-1",
        content="Look at **this** https://example.com/_test_ and @everyone",
        color=None,
        sent_at=datetime.now(timezone.utc),
        raw_tags={"badges": ""},
    )

    embed = build_tracking_embed(
        event=event,
        pattern=_build_pattern(color=None),
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color=None),
        thread=_build_thread(color=None),
    )

    assert "\\*\\*this\\*\\*" in embed.description
    assert "https://example.com/_test_" in embed.description
    assert "@everyone" not in embed.description


def test_tracking_view_links_to_twitch_channel() -> None:
    view = build_tracking_view(channel_login="example")

    assert len(view.children) == 1
    button = view.children[0]
    assert isinstance(button, discord.ui.Button)
    assert button.url == "https://www.twitch.tv/example"
