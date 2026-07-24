from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.config import AppConfig
from src.entrypoints.twitch_irc import TwitchIRCEntrypoint, build_chat_message_event, parse_irc_message
from src.events.twitch_events import TwitchChatMessageEvent
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
    assert event.message_kind == "privmsg"


def test_build_chat_message_event_normalizes_ctcp_action_payload() -> None:
    raw_line = (
        "@display-name=TestUser;color=#1E90FF;id=abc123;room-id=999;user-id=777;tmi-sent-ts=1710000000000 "
        ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #example :\x01ACTION waves hello\x01"
    )

    event = build_chat_message_event(parse_irc_message(raw_line))

    assert event is not None
    assert event.content == "waves hello"
    assert event.message_kind == "action"


def test_build_chat_message_event_maps_usernotice_with_system_and_user_text() -> None:
    raw_line = (
        "@badge-info=;badges=staff/1;color=#008000;display-name=ronni;emotes=;"
        "id=db25007f-7a18-43eb-9379-80131e44d633;login=ronni;msg-id=resub;"
        "room-id=12345678;subscriber=1;system-msg=ronni\\shas\\ssubscribed\\sfor\\s6\\smonths!;"
        "tmi-sent-ts=1507246572675;user-id=87654321 "
        ":tmi.twitch.tv USERNOTICE #dallas :Great stream -- keep it up!"
    )

    event = build_chat_message_event(parse_irc_message(raw_line))

    assert event is not None
    assert event.channel_login == "dallas"
    assert event.author_login == "ronni"
    assert event.author_display_name == "ronni"
    assert event.message_kind == "usernotice"
    assert event.notice_type == "resub"
    assert event.system_message == "ronni has subscribed for 6 months!"
    assert event.content == "ronni has subscribed for 6 months!\n\nGreat stream -- keep it up!"
    assert event.message_id == "db25007f-7a18-43eb-9379-80131e44d633"
    assert event.broadcaster_id == "12345678"
    assert event.author_id == "87654321"


def test_build_chat_message_event_maps_usernotice_without_user_text_to_system_message() -> None:
    raw_line = (
        "@badge-info=;badges=staff/1,premium/1;color=#0000FF;display-name=TWW2;emotes=;"
        "id=e9176cd8-5e22-4684-ad40-ce53c2561c5e;login=tww2;msg-id=subgift;"
        "room-id=19571752;subscriber=0;"
        "system-msg=TWW2\\sgifted\\sa\\sTier\\s1\\ssub\\sto\\sMr_Woodchuck!;"
        "tmi-sent-ts=1521159445153;user-id=87654321 "
        ":tmi.twitch.tv USERNOTICE #forstycup"
    )

    event = build_chat_message_event(parse_irc_message(raw_line))

    assert event is not None
    assert event.channel_login == "forstycup"
    assert event.author_login == "tww2"
    assert event.message_kind == "usernotice"
    assert event.notice_type == "subgift"
    assert event.system_message == "TWW2 gifted a Tier 1 sub to Mr_Woodchuck!"
    assert event.content == "TWW2 gifted a Tier 1 sub to Mr_Woodchuck!"


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
async def test_twitch_irc_entrypoint_forwards_usernotice_to_pipeline() -> None:
    config = AppConfig()
    processor = FakeMessageProcessor()
    entrypoint = TwitchIRCEntrypoint(AnonymousTwitchIRCGateway(config=config), message_processor=processor)

    await entrypoint.handle_line(
        "@display-name=ronni;id=db25007f-7a18-43eb-9379-80131e44d633;login=ronni;msg-id=resub;"
        "room-id=12345678;system-msg=ronni\\shas\\ssubscribed\\sfor\\s6\\smonths!;"
        "tmi-sent-ts=1507246572675;user-id=87654321 "
        ":tmi.twitch.tv USERNOTICE #dallas :Great stream -- keep it up!"
    )

    assert len(processor.messages) == 1
    assert processor.messages[0].message_kind == "usernotice"
    assert processor.messages[0].notice_type == "resub"
    assert processor.messages[0].content == "ronni has subscribed for 6 months!\n\nGreat stream -- keep it up!"


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
async def test_twitch_irc_gateway_logs_when_no_initial_channels_are_configured(caplog: pytest.LogCaptureFixture) -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)

    with caplog.at_level("DEBUG"):
        await gateway._join_initial_channels()

    assert "No initial Twitch IRC channels configured in runtime state" in caplog.text


@pytest.mark.asyncio
async def test_twitch_irc_gateway_read_loop_stops_on_connection_reset() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)

    class ResetReader:
        def at_eof(self) -> bool:
            return False

        async def readline(self) -> bytes:
            raise ConnectionResetError("reset by peer")

    gateway._reader = ResetReader()  # type: ignore[assignment]

    await gateway._read_loop()


@pytest.mark.asyncio
async def test_twitch_irc_gateway_stop_read_task_ignores_connection_reset() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    loop = asyncio.get_running_loop()
    gateway._read_task = loop.create_future()  # type: ignore[assignment]
    gateway._read_task.set_exception(ConnectionResetError("reset by peer"))

    await gateway._stop_read_task()

    assert gateway._read_task is None


@pytest.mark.asyncio
async def test_twitch_irc_gateway_close_connection_ignores_wait_closed_reset() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)

    class ResetWriter:
        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            raise ConnectionResetError("reset by peer")

    gateway._writer = ResetWriter()  # type: ignore[assignment]
    gateway._joined_channels.add("example")

    await gateway._close_connection(preserve_channels=True)

    assert gateway._writer is None
    assert gateway._pending_channels == {"example"}


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
