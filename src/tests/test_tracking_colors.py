from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

import discord
import pytest

from src.database.records import ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord, TwitchUserCacheRecord
from src.events.twitch_events import TwitchChatMessageEvent
from src.gateways.twitch_api import TwitchAPIError, TwitchUser
from src.localization import Localizer
from src.services.patterns import TrackingNotificationSender
from src.services.runtime_coordinator import TrackingRuntimeRelay
from src.services.tracking_delivery_queue import OrderedTrackingDeliveryService
from src.services.twitch_user_directory_service import TwitchUserDirectoryService
from src.tests.test_twitch_user_directory_service import FakeTwitchAPI, InMemoryTwitchUserCacheRepository, _wait_until
from src.utils.discord_embeds import TrackingEmbedRequest


def _record(user_id: str, color: str | None = None) -> TwitchUserCacheRecord:
    return TwitchUserCacheRecord(user_id, f"user{user_id}", f"User{user_id}", "https://example.test/avatar.png", "stored", color)


def _request(user_id: str = "1", target: int = 1000) -> TrackingEmbedRequest:
    return TrackingEmbedRequest(
        event=TwitchChatMessageEvent("channel", f"user{user_id}", "message", author_id=user_id),
        pattern=PatternRecord(1, 1, "message", "all", (), "all", (), "all", "all", False, False, None, False, 0),
        thread=ThreadRecord(1, 1, target, True, None),
        localizer=Localizer.from_directory(),
        channel=None,
    )


@dataclass
class _Sender(TrackingNotificationSender):
    sent: list[tuple[int, discord.Embed]] = field(default_factory=list)

    async def send_tracking_embed(self, discord_channel_id, embed, *, channel_login=None, thread_id=None) -> None:
        self.sent.append((discord_channel_id, embed))


@pytest.mark.asyncio
@pytest.mark.parametrize("color", ["#AA00BB", ""])
async def test_persisted_color_survives_restart_and_memory_eviction(color: str) -> None:
    repository = InMemoryTwitchUserCacheRepository(by_id={"1": _record("1", color), "2": _record("2", "#000000")})
    api = FakeTwitchAPI()
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
    assert await directory.get_user_chat_color_by_id("1") == color
    await directory.load_cached_user_by_id("2")
    assert directory.get_cached_user_by_id("1") is None
    assert await directory.get_user_chat_color_by_id("1") == color
    restarted = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
    assert await restarted.get_user_chat_color_by_id("1") == color
    assert api.color_requests == api.id_requests == []


@pytest.mark.asyncio
async def test_color_misses_are_batched_deduplicated_and_persisted_without_profile_requests() -> None:
    repository = InMemoryTwitchUserCacheRepository(by_id={str(index): _record(str(index)) for index in range(205)})
    api = FakeTwitchAPI(colors_by_id={user_id: "#AA00BB" for user_id in repository.by_id})
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=10)
    try:
        colors = await asyncio.gather(*(directory.get_user_chat_color_by_id(str(index % 205)) for index in range(410)))
        assert colors == ["#AA00BB"] * 410
        assert sorted(len(batch) for batch in api.color_requests) == [5, 100, 100]
        assert len({user_id for batch in api.color_requests for user_id in batch}) == 205
        assert all(record.chat_color == "#AA00BB" for record in repository.by_id.values())
        assert all(record.profile_image_url == "https://example.test/avatar.png" for record in repository.by_id.values())
        assert api.id_requests == api.id_color_requests == []
    finally:
        await directory.close()


@pytest.mark.asyncio
async def test_color_request_cancellation_does_not_cancel_other_waiters() -> None:
    repository = InMemoryTwitchUserCacheRepository(by_id={"1": _record("1")})
    api = FakeTwitchAPI(colors_by_id={"1": "#AA00BB"}, delay_seconds=0.05)
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
    first = asyncio.create_task(directory.get_user_chat_color_by_id("1"))
    second = asyncio.create_task(directory.get_user_chat_color_by_id("1"))
    try:
        await _wait_until(lambda: bool(api.color_requests))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second == "#AA00BB"
        assert api.color_requests == [("1",)]
    finally:
        await directory.close()


@pytest.mark.asyncio
async def test_empty_color_is_cached_but_omitted_users_remain_unknown() -> None:
    repository = InMemoryTwitchUserCacheRepository(by_id={"1": _record("1"), "2": _record("2")})
    api = FakeTwitchAPI(colors_by_id={"1": ""})
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=2)
    try:
        assert await asyncio.gather(directory.get_user_chat_color_by_id("1"), directory.get_user_chat_color_by_id("2")) == ["", None]
        assert await directory.get_user_chat_color_by_id("1") == ""
        api.colors_by_id["2"] = "#AA00BB"
        assert await directory.get_user_chat_color_by_id("2") == "#AA00BB"
        assert api.color_requests == [("1", "2"), ("2",)]
    finally:
        await directory.close()


@pytest.mark.asyncio
async def test_profile_only_refresh_keeps_known_color_in_memory_and_return_value() -> None:
    repository = InMemoryTwitchUserCacheRepository(by_id={"1": _record("1", "#AA00BB")})
    api = FakeTwitchAPI(users_by_id={"1": TwitchUser("1", "user1", "User1")})
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
    await directory.load_cached_user_by_id("1")
    directory._remember_api_users((api.users_by_id["1"],))
    assert directory.get_cached_user_by_id("1").chat_color == "#AA00BB"
    assert (await directory.refresh_user_by_id("1")).chat_color == "#AA00BB"


@pytest.mark.asyncio
async def test_partial_memory_record_still_uses_persisted_color_before_helix() -> None:
    repository = InMemoryTwitchUserCacheRepository(by_id={"1": _record("1", "#AA00BB")})
    api = FakeTwitchAPI()
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
    directory._remember_api_users((TwitchUser("1", "user1", "User1"),))
    assert await directory.get_user_chat_color_by_id("1") == "#AA00BB"
    assert api.color_requests == []


@pytest.mark.asyncio
async def test_slow_color_batch_does_not_block_later_batches_and_keeps_newer_irc_color() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class GatedAPI(FakeTwitchAPI):
        async def get_user_chat_colors_by_ids(self, user_ids):
            if "1" in user_ids:
                started.set()
                await release.wait()
            return await super().get_user_chat_colors_by_ids(user_ids)

    repository = InMemoryTwitchUserCacheRepository(by_id={"1": _record("1"), "2": _record("2")})
    api = GatedAPI(colors_by_id={"1": "#AA00BB", "2": "#123456"})
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
    first = asyncio.create_task(directory.get_user_chat_color_by_id("1"))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert await asyncio.wait_for(directory.get_user_chat_color_by_id("2"), timeout=1) == "#123456"
        assert not first.done()
        await directory.observe_chat_message(TwitchChatMessageEvent("channel", "user1", "message", author_id="1", color="#654321"))
        release.set()
        assert await first == "#654321"
        assert repository.by_id["1"].chat_color == "#654321"
    finally:
        release.set()
        await directory.close()


@dataclass
class _GatedColors:
    release: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def get_user_chat_color_by_id(self, user_id: str) -> str:
        if user_id == "slow":
            self.started.set()
            await self.release.wait()
        return "#AA00BB"


@pytest.mark.asyncio
async def test_many_waiting_colors_only_block_their_own_discord_target() -> None:
    colors = _GatedColors()
    sender = _Sender()
    queue = OrderedTrackingDeliveryService(sender=sender, twitch_colors=colors, per_target_rate_per_second=0)
    relay = TrackingRuntimeRelay(sender=queue)
    await queue.start()
    try:
        for _ in range(20):
            await relay.send_tracking_notification(1000, _request("slow"))
        await asyncio.wait_for(colors.started.wait(), timeout=1)
        await relay.send_tracking_notification(1000, _request("ready"))
        await relay.send_tracking_notification(2000, _request("ready", 2000))
        await _wait_until(lambda: len(sender.sent) == 1)
        assert sender.sent[0][0] == 2000
        assert sender.sent[0][1].color.value == 0xAA00BB
        colors.release.set()
        await _wait_until(lambda: len(sender.sent) == 22)
        assert all(embed.color.value == 0xAA00BB for _, embed in sender.sent)
    finally:
        colors.release.set()
        await queue.stop()


@pytest.mark.asyncio
async def test_colors_for_multiple_pings_in_one_target_are_prefetched_together() -> None:
    repository = InMemoryTwitchUserCacheRepository(by_id={str(index): _record(str(index)) for index in range(3)})
    api = FakeTwitchAPI(colors_by_id={user_id: "#AA00BB" for user_id in repository.by_id})
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=3)
    sender = _Sender()
    queue = OrderedTrackingDeliveryService(sender=sender, twitch_colors=directory, per_target_rate_per_second=0)
    await queue.start()
    try:
        for index in range(3):
            await queue.send_tracking_notification(1000, _request(str(index)))
        await _wait_until(lambda: len(sender.sent) == 3)
        assert api.color_requests == [("0", "1", "2")]
        assert all(embed.color.value == 0xAA00BB for _, embed in sender.sent)
        assert [embed.author.name for _, embed in sender.sent] == ["user0", "user1", "user2"]
    finally:
        await queue.stop()
        await directory.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("color, expected", [("", 0x808080), ("#000000", 0x000000)])
async def test_confirmed_empty_and_black_colors_send_without_retry_and_keep_auto_reply(color, expected) -> None:
    repository = InMemoryTwitchUserCacheRepository(by_id={"1": _record("1")})
    api = FakeTwitchAPI(colors_by_id={"1": color})
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
    sender = _Sender()
    queue = OrderedTrackingDeliveryService(sender=sender, twitch_colors=directory)
    request = replace(_request(), reply=ReplyRecord(1, 1, "response", False, False))
    try:
        await asyncio.wait_for(queue.send_tracking_notification(1000, request), timeout=1)
        assert sender.sent[0][1].color.value == expected
        assert sender.sent[0][1].fields[0].value == request.reply.reply_message
        assert api.color_requests == [("1",)]
    finally:
        await directory.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["pattern", "channel", "thread", "irc"])
async def test_explicit_and_irc_colors_skip_color_lookup(source: str) -> None:
    class UnexpectedLookup:
        async def get_user_chat_color_by_id(self, user_id: str) -> str:
            pytest.fail("No lookup needed for an already resolved color")

    request = _request()
    color = "#123456"
    if source == "pattern":
        request = replace(request, pattern=replace(request.pattern, color=color))
    elif source == "channel":
        request = replace(request, channel=ChannelRecord(1, "42", color))
    elif source == "thread":
        request = replace(request, thread=replace(request.thread, color=color))
    else:
        request = replace(request, event=replace(request.event, color=color))
    sender = _Sender()
    queue = OrderedTrackingDeliveryService(sender=sender, twitch_colors=UnexpectedLookup())
    await queue.send_tracking_notification(1000, request)
    assert sender.sent[0][1].color.value == 0x123456


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "omitted"])
async def test_color_api_error_waits_and_retries_before_sending(caplog, failure) -> None:
    class FailingAPI(FakeTwitchAPI):
        async def get_user_chat_colors_by_ids(self, user_ids):
            if not self.colors_by_id and failure == "error":
                raise TwitchAPIError("Unavailable")
            return await super().get_user_chat_colors_by_ids(user_ids)

    repository = InMemoryTwitchUserCacheRepository(by_id={"1": _record("1")})
    api = FailingAPI()
    directory = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
    sender = _Sender()
    queue = OrderedTrackingDeliveryService(sender=sender, twitch_colors=directory)
    sending = asyncio.create_task(queue.send_tracking_notification(1000, _request()))
    try:
        await _wait_until(lambda: "user_id=1" in caplog.text)
        assert sender.sent == []
        assert repository.by_id["1"].chat_color is None
        api.colors_by_id["1"] = "#AA00BB"
        await asyncio.wait_for(sending, timeout=2)
        assert sender.sent[0][1].color.value == 0xAA00BB
    finally:
        sending.cancel()
        await asyncio.gather(sending, return_exceptions=True)
        await directory.close()


@pytest.mark.asyncio
async def test_shutdown_cancels_waiting_color_work() -> None:
    colors = _GatedColors()
    queue = OrderedTrackingDeliveryService(sender=_Sender(), twitch_colors=colors, stop_timeout_seconds=0.1)
    await queue.start()
    await queue.send_tracking_notification(1000, _request("slow"))
    await asyncio.wait_for(colors.started.wait(), timeout=1)
    await asyncio.wait_for(queue.stop(), timeout=1)
    assert not queue._preparation_tasks
