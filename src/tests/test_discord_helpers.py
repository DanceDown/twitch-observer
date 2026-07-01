from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import dataclass, field
from types import SimpleNamespace

import aiohttp
import discord
import pytest

from src.database.records import ChannelRecord, PatternRecord, ThreadRecord
from src.entrypoints.discord.helpers import build_public_result_embed, complete_bound_result, send_initial_result
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.twitch_events import TwitchChatMessageEvent
from src.localization import Localizer
from src.utils.discord_embeds import build_channel_event_auto_reply_embed, build_result_embed, build_tracking_embed


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


class FakeUnknownInteractionError(discord.NotFound):
    code = 10062

    def __init__(self) -> None:
        pass


@dataclass
class FakeResponse:
    done: bool = False
    fail_defer: bool = False

    def is_done(self) -> bool:
        return self.done

    async def defer(self, *, ephemeral: bool = False) -> None:
        _ = ephemeral
        if self.fail_defer:
            raise FakeUnknownInteractionError()
        self.done = True

    async def send_message(self, *, embed: discord.Embed, ephemeral: bool, view: object | None = None) -> None:
        _ = (embed, ephemeral, view)
        self.done = True


@dataclass
class FakeChannel:
    sent_embeds: list[discord.Embed] = field(default_factory=list)
    send_failures_before_success: int = 0

    async def send(self, *, embed: discord.Embed) -> None:
        if self.send_failures_before_success > 0:
            self.send_failures_before_success -= 1
            raise aiohttp.ClientConnectionError("temporary send failure")
        self.sent_embeds.append(embed)


@dataclass
class FakeBoundMessage:
    edited_embed: discord.Embed | None = None
    edited_view: object | None = None
    deleted: bool = False

    async def edit(self, *, embed: discord.Embed | None = None, view: object | None = None) -> None:
        self.edited_embed = embed
        self.edited_view = view

    async def delete(self) -> None:
        self.deleted = True


@dataclass
class FakeInteraction:
    response: FakeResponse
    channel: FakeChannel | None = None
    locale: str = "en-US"
    user: object = field(default_factory=lambda: SimpleNamespace(id=123))
    deleted_original_response: bool = False
    edited_original_embed: discord.Embed | None = None

    async def edit_original_response(self, *, embed: discord.Embed) -> None:
        self.edited_original_embed = embed

    async def delete_original_response(self) -> None:
        self.deleted_original_response = True


@pytest.mark.asyncio
async def test_send_initial_result_posts_public_result_even_when_defer_hits_unknown_interaction() -> None:
    interaction = FakeInteraction(
        response=FakeResponse(done=False, fail_defer=True),
        channel=FakeChannel(),
    )
    result = DiscordCommandResult(
        title="Ping Added",
        message="Added a ping.",
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    await send_initial_result(interaction, result)

    assert interaction.channel is not None
    assert len(interaction.channel.sent_embeds) == 1
    assert interaction.channel.sent_embeds[0].description == "Added a ping."
    assert interaction.deleted_original_response is False


@pytest.mark.asyncio
async def test_complete_bound_result_posts_public_result_even_when_defer_hits_unknown_interaction() -> None:
    interaction = FakeInteraction(
        response=FakeResponse(done=False, fail_defer=True),
        channel=FakeChannel(),
    )
    bound_message = FakeBoundMessage()
    result = DiscordCommandResult(
        title="Ping Added",
        message="Added a ping.",
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    await complete_bound_result(interaction, bound_message=bound_message, result=result)

    assert interaction.channel is not None
    assert len(interaction.channel.sent_embeds) == 1
    assert bound_message.deleted is True


@pytest.mark.asyncio
async def test_send_initial_result_retries_transient_public_send_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setenv("DISCORD_DELIVERY_MAX_ATTEMPTS", "3")
    monkeypatch.setattr("src.entrypoints.discord.delivery.asyncio.sleep", fake_sleep)
    interaction = FakeInteraction(
        response=FakeResponse(done=False, fail_defer=False),
        channel=FakeChannel(send_failures_before_success=1),
    )
    result = DiscordCommandResult(
        title="Ping Added",
        message="Added a ping.",
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    await send_initial_result(interaction, result)

    assert interaction.channel is not None
    assert len(interaction.channel.sent_embeds) == 1
    assert interaction.deleted_original_response is True
    assert interaction.edited_original_embed is None


@pytest.mark.asyncio
async def test_send_initial_result_keeps_result_visible_when_public_send_never_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setenv("DISCORD_DELIVERY_MAX_ATTEMPTS", "3")
    monkeypatch.setattr("src.entrypoints.discord.delivery.asyncio.sleep", fake_sleep)
    interaction = FakeInteraction(
        response=FakeResponse(done=False, fail_defer=False),
        channel=FakeChannel(send_failures_before_success=3),
    )
    result = DiscordCommandResult(
        title="Ping Added",
        message="Added a ping.",
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    await send_initial_result(interaction, result)

    assert interaction.channel is not None
    assert interaction.channel.sent_embeds == []
    assert interaction.deleted_original_response is False
    assert interaction.edited_original_embed is not None
    assert interaction.edited_original_embed.description == "Added a ping."


@pytest.mark.asyncio
async def test_complete_bound_result_keeps_bound_message_when_public_send_never_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setenv("DISCORD_DELIVERY_MAX_ATTEMPTS", "3")
    monkeypatch.setattr("src.entrypoints.discord.delivery.asyncio.sleep", fake_sleep)
    interaction = FakeInteraction(
        response=FakeResponse(done=False, fail_defer=False),
        channel=FakeChannel(send_failures_before_success=3),
    )
    bound_message = FakeBoundMessage()
    result = DiscordCommandResult(
        title="Ping Added",
        message="Added a ping.",
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    await complete_bound_result(interaction, bound_message=bound_message, result=result)

    assert interaction.channel is not None
    assert interaction.channel.sent_embeds == []
    assert interaction.deleted_original_response is False
    assert bound_message.deleted is False
    assert bound_message.edited_embed is not None
    assert bound_message.edited_embed.description == "Added a ping."


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


def test_result_embed_supports_author_and_thumbnail_metadata() -> None:
    embed = build_result_embed(
        DiscordCommandResult(
            title="Channel Is Live",
            message="ExampleChannel is now live",
            thumbnail_url="https://example.test/channel.png",
            author_name="Channel_*Name*",
            author_url="https://www.twitch.tv/channel",
            author_icon_url="https://example.test/channel.png",
        )
    )

    assert embed.author.name == "Channel_*Name*"
    assert embed.author.url == "https://www.twitch.tv/channel"
    assert embed.author.icon_url == "https://example.test/channel.png"
    assert embed.thumbnail.url == "https://example.test/channel.png"


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
