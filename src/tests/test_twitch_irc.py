from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.config import AppConfig
from src.entrypoints.twitch_irc import TwitchIRCEntrypoint, build_chat_message_event, parse_irc_message
from src.events.event_types import TwitchChatMessageEvent
from src.gateways.twitch_irc import AnonymousTwitchIRCGateway


@dataclass
class FakeMessageProcessor:
    messages: list[TwitchChatMessageEvent] = field(default_factory=list)

    async def process(self, message: TwitchChatMessageEvent) -> None:
        self.messages.append(message)


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


def test_build_chat_message_event_normalizes_ctcp_action_payload() -> None:
    raw_line = (
        "@display-name=TestUser;color=#1E90FF;id=abc123;room-id=999;user-id=777;tmi-sent-ts=1710000000000 "
        ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #example :\x01ACTION waves hello\x01"
    )

    event = build_chat_message_event(parse_irc_message(raw_line))

    assert event is not None
    assert event.content == "waves hello"


@pytest.mark.asyncio
async def test_twitch_irc_entrypoint_forwards_privmsg_to_pipeline() -> None:
    config = AppConfig()
    processor = FakeMessageProcessor()
    entrypoint = TwitchIRCEntrypoint(AnonymousTwitchIRCGateway(config=config), message_processor=processor)

    await entrypoint.handle_line(
        "@display-name=TestUser;id=abc123;room-id=999;user-id=777;tmi-sent-ts=1710000000000 "
        ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #example :Hello world!"
    )

    assert len(processor.messages) == 1
    assert processor.messages[0].content == "Hello world!"


@pytest.mark.asyncio
async def test_twitch_irc_entrypoint_ignores_non_privmsg_lines() -> None:
    config = AppConfig()
    processor = FakeMessageProcessor()
    entrypoint = TwitchIRCEntrypoint(AnonymousTwitchIRCGateway(config=config), message_processor=processor)

    await entrypoint.handle_line(":tmi.twitch.tv NOTICE * :Improperly formatted auth")

    assert processor.messages == []


@pytest.mark.asyncio
async def test_twitch_irc_gateway_can_join_channels_later() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    gateway._reader = SimpleNamespace(at_eof=lambda: False)  # type: ignore[assignment]
    gateway._writer = SimpleNamespace(is_closing=lambda: False)  # type: ignore[assignment]
    gateway._send_line = fake_send_line  # type: ignore[method-assign]

    await gateway.join_channel("Example")
    await gateway.join_channel("#example")
    await gateway.join_channel("second")

    assert sent_lines == ["JOIN #example", "JOIN #second"]


@pytest.mark.asyncio
async def test_twitch_irc_gateway_rejoins_pending_channels_after_connect() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    gateway._pending_channels.add("example")
    gateway._pending_channels.add("second")
    gateway._send_line = fake_send_line  # type: ignore[method-assign]

    await gateway._join_initial_channels()

    assert sent_lines == ["JOIN #example", "JOIN #second"]


@pytest.mark.asyncio
async def test_twitch_irc_gateway_reconnects_before_join_when_read_loop_stopped() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines: list[str] = []
    reconnects: list[str] = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    async def fake_ensure_connected() -> None:
        reconnects.append("reconnected")
        gateway._read_task = None

    loop = asyncio.get_running_loop()
    gateway._reader = SimpleNamespace(at_eof=lambda: False)  # type: ignore[assignment]
    gateway._writer = SimpleNamespace(is_closing=lambda: False)  # type: ignore[assignment]
    gateway._read_task = loop.create_future()  # type: ignore[assignment]
    gateway._read_task.set_result(None)
    gateway._send_line_with_reconnect = fake_send_line  # type: ignore[method-assign]
    gateway.ensure_connected = fake_ensure_connected  # type: ignore[method-assign]

    await gateway.join_channel("Example")

    assert reconnects == ["reconnected"]
    assert sent_lines == ["JOIN #example"]


@pytest.mark.asyncio
async def test_twitch_irc_gateway_sends_pass_during_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
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

    monkeypatch.setattr("src.gateways.twitch_irc.asyncio.open_connection", fake_open_connection)

    await gateway._open_connection()

    assert sent_lines[0] == "PASS SCHMOOPIIE"
    assert sent_lines[1].startswith("CAP REQ :twitch.tv/tags twitch.tv/commands")
