from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.adapters.twitch_irc import AnonymousTwitchIRCAdapter, build_chat_message_event, parse_irc_message
from src.config import AppConfig
from src.events.event_bus import EventBus
from src.events.event_types import EventType


def test_parse_irc_message_parses_twitch_tags_and_payload() -> None:
    raw_line = (
        "@badge-info=;badges=;color=#1E90FF;display-name=TestUser;emotes=;id=abc123;"
        "room-id=999;user-id=777;tmi-sent-ts=1710000000000 "
        ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #example :Hello world!"
    )

    message = parse_irc_message(raw_line)

    assert message.command == "PRIVMSG"
    assert message.params == ["#example"]
    assert message.trailing == "Hello world!"
    assert message.tags["display-name"] == "TestUser"
    assert message.tags["room-id"] == "999"


def test_build_chat_message_event_maps_irc_privmsg_to_domain_event() -> None:
    raw_line = (
        "@display-name=TestUser;color=#1E90FF;id=abc123;reply-parent-msg-id=def456;"
        "room-id=999;user-id=777;tmi-sent-ts=1710000000000 "
        ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #example :Hello world!"
    )

    event = build_chat_message_event(parse_irc_message(raw_line))

    assert event is not None
    assert event.channel_login == "example"
    assert event.author_login == "testuser"
    assert event.author_display_name == "TestUser"
    assert event.message_id == "abc123"
    assert event.reply_parent_message_id == "def456"
    assert event.broadcaster_id == "999"
    assert event.author_id == "777"


@pytest.mark.asyncio
async def test_anonymous_adapter_emits_bus_event_for_privmsg() -> None:
    bus = EventBus()
    config = AppConfig(twitch_irc_channels=["example"])
    adapter = AnonymousTwitchIRCAdapter(config=config, event_bus=bus)
    captured = []

    bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, lambda event: captured.append(event))

    await adapter.handle_line(
        "@display-name=TestUser;id=abc123;room-id=999;user-id=777;tmi-sent-ts=1710000000000 "
        ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #example :Hello world!"
    )

    assert len(captured) == 1
    assert captured[0].content == "Hello world!"


@pytest.mark.asyncio
async def test_anonymous_adapter_ignores_non_privmsg_lines() -> None:
    bus = EventBus()
    config = AppConfig()
    adapter = AnonymousTwitchIRCAdapter(config=config, event_bus=bus)
    captured = []

    bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, lambda event: captured.append(event))

    await adapter.handle_line(":tmi.twitch.tv NOTICE * :Improperly formatted auth")

    assert captured == []


@pytest.mark.asyncio
async def test_anonymous_adapter_can_join_channels_later() -> None:
    bus = EventBus()
    config = AppConfig()
    adapter = AnonymousTwitchIRCAdapter(config=config, event_bus=bus)
    sent_lines = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    adapter._writer = SimpleNamespace()  # type: ignore[assignment]
    adapter._send_line = fake_send_line  # type: ignore[method-assign]

    await adapter.join_channel("Example")
    await adapter.join_channel("#example")
    await adapter.join_channel("second")

    assert sent_lines == ["JOIN #example", "JOIN #second"]


@pytest.mark.asyncio
async def test_anonymous_adapter_queues_channel_joins_until_connected() -> None:
    bus = EventBus()
    config = AppConfig()
    adapter = AnonymousTwitchIRCAdapter(config=config, event_bus=bus)
    sent_lines = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    await adapter.join_channel("Example")
    adapter._writer = SimpleNamespace()  # type: ignore[assignment]
    adapter._send_line = fake_send_line  # type: ignore[method-assign]

    await adapter.join_channels(["example", "second"])

    assert sent_lines == ["JOIN #example", "JOIN #second"]


@pytest.mark.asyncio
async def test_anonymous_adapter_sends_pass_during_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = EventBus()
    config = AppConfig()
    adapter = AnonymousTwitchIRCAdapter(config=config, event_bus=bus)
    sent_lines: list[str] = []

    class FakeReader:
        def at_eof(self) -> bool:
            return True

        async def readline(self) -> bytes:
            return b""

    class FakeWriter:
        def write(self, data: bytes) -> None:
            sent_lines.append(data.decode("utf-8").strip())

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def fake_open_connection(*args, **kwargs):
        return FakeReader(), FakeWriter()

    monkeypatch.setattr("src.adapters.twitch_irc.asyncio.open_connection", fake_open_connection)

    await adapter.start()

    assert sent_lines[0] == "PASS SCHMOOPIIE"
    assert sent_lines[1].startswith("CAP REQ :twitch.tv/tags twitch.tv/commands")
