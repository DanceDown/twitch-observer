from __future__ import annotations

from datetime import UTC, datetime

from src.database.records import ChannelRecord, PatternRecord, ThreadRecord
from src.entrypoints.discord.helpers import build_public_result_embed
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.twitch_events import TwitchChatMessageEvent
from src.localization import Localizer
from src.utils.discord_embeds import build_channel_event_auto_reply_embed, build_tracking_embed


def test_public_actor_embed_keeps_direct_user_placeholder_without_duplicate_prefix() -> None:
    localizer = Localizer.from_directory()
    message = localizer._interpolate(  # type: ignore[attr-defined]
        "<@{RAW:view.requester_id}> added a ping: `{CODE:view.ping}`",
        {"view": {"requester_id": "123", "ping": "alpha"}},
        language=None,
        placeholder_specs=None,
    )
    result = DiscordCommandResult(
        title="Ping Added",
        message=message,
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    embed = build_public_result_embed(result)

    assert embed.description is not None
    assert embed.description.count("<@123>") == 1
    assert "`alpha`" in embed.description


def test_public_actor_embed_keeps_plain_body_when_no_user_placeholder_exists() -> None:
    result = DiscordCommandResult(
        title="Ping Added",
        message="Added a ping.",
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    embed = build_public_result_embed(result)

    assert embed.description is not None
    assert embed.description == "Added a ping."


def test_tracking_embed_author_name_is_not_escaped() -> None:
    embed = build_tracking_embed(
        event=_event(author_display_name="User_*Name*"),
        pattern=_pattern(),
        thread=_thread(),
        localizer=Localizer.from_directory(),
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color=None),
    )

    assert embed.author.name == "User_*Name*"


def test_channel_event_embed_author_name_is_not_escaped() -> None:
    embed = build_channel_event_auto_reply_embed(
        thread=_thread(),
        localizer=Localizer.from_directory(),
        channel_display_name="Channel_*Name*",
        channel_login="channel",
        state="online",
        reply_message="Hello",
        channel=ChannelRecord(thread_id=1, twitch_channel_id="42", color=None),
        event_color=None,
    )

    assert embed.author.name == "Channel_*Name*"


def _thread() -> ThreadRecord:
    return ThreadRecord(
        thread_id=1,
        owner_id=1,
        discord_channel_id=99,
        enabled=True,
        color=None,
        language="english",
    )


def _pattern() -> PatternRecord:
    return PatternRecord(
        thread_id=1,
        pattern_id=1,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=1,
    )


def _event(*, author_display_name: str) -> TwitchChatMessageEvent:
    return TwitchChatMessageEvent(
        channel_login="channel",
        broadcaster_id="42",
        author_login="user_name",
        author_display_name=author_display_name,
        author_id="7",
        content="hello",
        message_id="msg-1",
        sent_at=datetime.now(UTC),
    )
