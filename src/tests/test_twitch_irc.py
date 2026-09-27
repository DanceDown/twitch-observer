from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

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

    async def enqueue(self, message: TwitchChatMessageEvent) -> None:
        self.messages.append(message)


def _reader(fake: object) -> asyncio.StreamReader:
    return cast(asyncio.StreamReader, fake)


def _writer(fake: object) -> asyncio.StreamWriter:
    return cast(asyncio.StreamWriter, fake)


def _read_task(fake: asyncio.Future[None]) -> asyncio.Task[None]:
    return cast(asyncio.Task[None], fake)


def _bind_send_line(
    gateway: AnonymousTwitchIRCGateway,
    send_line: Callable[[str], Awaitable[None]],
) -> None:
    gateway._send_line = send_line


def _bind_send_line_with_reconnect(
    gateway: AnonymousTwitchIRCGateway,
    send_line: Callable[[str], Awaitable[None]],
) -> None:
    gateway._send_line_with_reconnect = send_line


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

    gateway._reader = _reader(SimpleNamespace(at_eof=lambda: False))
    gateway._writer = _writer(SimpleNamespace(is_closing=lambda: False))
    _bind_send_line(gateway, fake_send_line)

    await gateway.join_channels(["Example", "#example", "second"])

    assert sent_lines == ["JOIN #example,#second"]
    assert gateway._joined_channels == set()
    assert gateway._pending_channels == {"example", "second"}


@pytest.mark.asyncio
async def test_twitch_irc_gateway_keeps_batched_join_pending_when_connect_fails() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)

    async def fake_ensure_connected() -> None:
        raise ConnectionError("connect failed")

    gateway.ensure_connected = fake_ensure_connected

    with pytest.raises(ConnectionError):
        await gateway.join_channels(["Example", "Second"])

    assert gateway._pending_channels == {"example", "second"}


@pytest.mark.asyncio
async def test_twitch_irc_gateway_confirms_join_from_roomstate() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    handled_lines: list[str] = []

    class Reader:
        def __init__(self) -> None:
            self.lines = [
                b"@emote-only=0;followers-only=-1;r9k=0;room-id=42;slow=0;subs-only=0 :tmi.twitch.tv ROOMSTATE #Example\r\n",
            ]
            self.index = 0

        def at_eof(self) -> bool:
            return self.index >= len(self.lines)

        async def readline(self) -> bytes:
            line = self.lines[self.index]
            self.index += 1
            return line

    async def fake_line_handler(raw_line: str) -> None:
        handled_lines.append(raw_line.strip())

    gateway._reader = _reader(Reader())
    gateway._line_handler = fake_line_handler
    gateway._pending_channels.add("example")
    gateway._pending_join_sent_at["example"] = 1

    await gateway._read_loop()

    assert gateway._joined_channels == {"example"}
    assert gateway._pending_channels == set()
    assert gateway._pending_join_sent_at == {}
    assert handled_lines == ["@emote-only=0;followers-only=-1;r9k=0;room-id=42;slow=0;subs-only=0 :tmi.twitch.tv ROOMSTATE #Example"]


@pytest.mark.asyncio
async def test_twitch_irc_gateway_confirms_batched_joins_from_individual_roomstates() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)

    class Reader:
        def __init__(self) -> None:
            self.lines = [
                b"@room-id=42 :tmi.twitch.tv ROOMSTATE #example\r\n",
                b"@room-id=84 :tmi.twitch.tv ROOMSTATE #second\r\n",
            ]
            self.index = 0

        def at_eof(self) -> bool:
            return self.index >= len(self.lines)

        async def readline(self) -> bytes:
            line = self.lines[self.index]
            self.index += 1
            return line

    gateway._reader = _reader(Reader())
    gateway._pending_channels.update({"example", "second"})
    gateway._pending_join_sent_at["example"] = 1
    gateway._pending_join_sent_at["second"] = 1

    await gateway._read_loop()

    assert gateway._joined_channels == {"example", "second"}
    assert gateway._pending_channels == set()
    assert gateway._pending_join_sent_at == {}


@pytest.mark.asyncio
async def test_twitch_irc_gateway_rejoins_pending_channels_after_connect() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    gateway._pending_channels.add("example")
    gateway._pending_channels.add("second")
    _bind_send_line(gateway, fake_send_line)

    await gateway._join_initial_channels()

    assert sent_lines == ["JOIN #example,#second"]


@pytest.mark.asyncio
async def test_twitch_irc_gateway_splits_large_join_batches() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines: list[str] = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    channel_logins = [f"channel{i:02d}{'x' * 20}" for i in range(30)]
    _bind_send_line(gateway, fake_send_line)

    await gateway._send_join_batches(channel_logins, reconnect=False)

    assert len(sent_lines) > 1
    assert all(line.startswith("JOIN #") for line in sent_lines)
    assert all(len(line) <= 480 for line in sent_lines)
    joined_from_lines = {item.lstrip("#") for line in sent_lines for item in line.removeprefix("JOIN ").split(",")}
    assert joined_from_lines == set(channel_logins)


@pytest.mark.asyncio
async def test_twitch_irc_gateway_can_part_channels_later() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines: list[str] = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    gateway._reader = _reader(SimpleNamespace(at_eof=lambda: False))
    gateway._writer = _writer(SimpleNamespace(is_closing=lambda: False))
    gateway._joined_channels.update({"example", "second"})
    gateway._pending_channels.add("pending")
    gateway._pending_join_sent_at["pending"] = 1
    _bind_send_line_with_reconnect(gateway, fake_send_line)

    await gateway.leave_channels(["Example", "#second", "pending", "missing"])

    assert sent_lines == ["PART #example,#pending,#second"]
    assert gateway._joined_channels == set()
    assert gateway._pending_channels == set()
    assert gateway._pending_join_sent_at == {}


@pytest.mark.asyncio
async def test_twitch_irc_gateway_splits_large_part_batches() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines: list[str] = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    channel_logins = [f"channel{i:02d}{'x' * 20}" for i in range(30)]
    gateway._joined_channels.update(channel_logins)
    _bind_send_line(gateway, fake_send_line)

    await gateway._send_part_batches(channel_logins, reconnect=False)

    assert len(sent_lines) > 1
    assert all(line.startswith("PART #") for line in sent_lines)
    assert all(len(line) <= 480 for line in sent_lines)
    parted_from_lines = {item.lstrip("#") for line in sent_lines for item in line.removeprefix("PART ").split(",")}
    assert parted_from_lines == set(channel_logins)
    assert gateway._joined_channels == set()


@pytest.mark.asyncio
async def test_twitch_irc_gateway_keeps_pending_channel_when_join_fails() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines: list[str] = []

    async def failing_send_line(line: str) -> None:
        sent_lines.append(line)
        raise BrokenPipeError("pipe closed")

    gateway._pending_channels.add("example")
    _bind_send_line(gateway, failing_send_line)

    with pytest.raises(BrokenPipeError):
        await gateway._join_initial_channels()

    assert sent_lines == ["JOIN #example"]
    assert gateway._pending_channels == {"example"}


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

    gateway._reader = _reader(ResetReader())

    await gateway._read_loop()


@pytest.mark.asyncio
async def test_twitch_irc_gateway_answers_ping_before_line_handler() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    handled_lines: list[str] = []
    sent_lines: list[str] = []

    class Reader:
        def __init__(self) -> None:
            self.lines = [
                b"PING :tmi.twitch.tv\r\n",
                b":tmi.twitch.tv NOTICE * :hello\r\n",
            ]
            self.index = 0

        def at_eof(self) -> bool:
            return self.index >= len(self.lines)

        async def readline(self) -> bytes:
            line = self.lines[self.index]
            self.index += 1
            return line

    async def fake_line_handler(raw_line: str) -> None:
        handled_lines.append(raw_line.strip())

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    gateway._reader = _reader(Reader())
    gateway._line_handler = fake_line_handler
    _bind_send_line(gateway, fake_send_line)

    await gateway._read_loop()

    assert sent_lines == ["PONG :tmi.twitch.tv"]
    assert handled_lines == [":tmi.twitch.tv NOTICE * :hello"]


@pytest.mark.asyncio
async def test_twitch_irc_gateway_observes_health_pong_before_line_handler() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    handled_lines: list[str] = []

    class Reader:
        def __init__(self) -> None:
            self.lines = [
                b":tmi.twitch.tv PONG tmi.twitch.tv :health-123\r\n",
                b":tmi.twitch.tv NOTICE * :hello\r\n",
            ]
            self.index = 0

        def at_eof(self) -> bool:
            return self.index >= len(self.lines)

        async def readline(self) -> bytes:
            line = self.lines[self.index]
            self.index += 1
            return line

    async def fake_line_handler(raw_line: str) -> None:
        handled_lines.append(raw_line.strip())

    gateway._reader = _reader(Reader())
    gateway._line_handler = fake_line_handler
    gateway._pending_health_ping_payload = "health-123"
    gateway._pending_health_ping_sent_at = asyncio.get_running_loop().time()

    await gateway._read_loop()

    assert gateway._pending_health_ping_payload is None
    assert gateway._pending_health_ping_sent_at is None
    assert handled_lines == [":tmi.twitch.tv NOTICE * :hello"]


@pytest.mark.asyncio
async def test_twitch_irc_gateway_sends_health_ping_after_idle() -> None:
    config = AppConfig(twitch_irc_health_ping_interval_seconds=1)
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines: list[str] = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    _bind_send_line_with_reconnect(gateway, fake_send_line)
    gateway._last_line_received_at = asyncio.get_running_loop().time() - 2

    await gateway._health_check_once()

    assert len(sent_lines) == 1
    assert sent_lines[0].startswith("PING :health-")
    assert gateway._pending_health_ping_payload == sent_lines[0].removeprefix("PING :")
    assert gateway._pending_health_ping_sent_at is not None


@pytest.mark.asyncio
async def test_twitch_irc_gateway_refreshes_joins_after_health_ping_timeout() -> None:
    config = AppConfig(twitch_irc_health_ping_interval_seconds=1, twitch_irc_health_ping_timeout_seconds=1)
    gateway = AnonymousTwitchIRCGateway(config=config)
    sent_lines: list[str] = []

    async def fake_send_line(line: str) -> None:
        sent_lines.append(line)

    _bind_send_line_with_reconnect(gateway, fake_send_line)
    gateway._joined_channels.update({"example", "second"})
    gateway._pending_health_ping_payload = "health-123"
    gateway._pending_health_ping_sent_at = asyncio.get_running_loop().time() - 2

    await gateway._health_check_once()

    assert sent_lines == ["JOIN #example,#second"]
    assert gateway._pending_channels == {"example", "second"}
    assert gateway._pending_health_ping_payload is None
    assert gateway._pending_health_ping_sent_at is None


@pytest.mark.asyncio
async def test_twitch_irc_gateway_stops_read_loop_on_reconnect_command() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    handled_lines: list[str] = []

    class Reader:
        def __init__(self) -> None:
            self.lines = [
                b":tmi.twitch.tv RECONNECT\r\n",
                b":tmi.twitch.tv NOTICE * :should not be handled\r\n",
            ]
            self.index = 0

        def at_eof(self) -> bool:
            return self.index >= len(self.lines)

        async def readline(self) -> bytes:
            line = self.lines[self.index]
            self.index += 1
            return line

    async def fake_line_handler(raw_line: str) -> None:
        handled_lines.append(raw_line.strip())

    gateway._reader = _reader(Reader())
    gateway._line_handler = fake_line_handler

    await gateway._read_loop()

    assert handled_lines == []


@pytest.mark.asyncio
async def test_twitch_irc_gateway_stop_read_task_ignores_connection_reset() -> None:
    config = AppConfig()
    gateway = AnonymousTwitchIRCGateway(config=config)
    loop = asyncio.get_running_loop()
    gateway._read_task = _read_task(loop.create_future())
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

    gateway._writer = _writer(ResetWriter())
    gateway._joined_channels.add("example")

    await gateway._close_connection(preserve_channels=True)

    assert gateway._writer is None
    assert gateway._pending_channels == {"example"}


@pytest.mark.asyncio
async def test_twitch_irc_gateway_start_retries_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(
        twitch_irc_connection_check_interval_seconds=0.01,
        twitch_irc_reconnect_initial_delay_seconds=0.01,
        twitch_irc_reconnect_max_delay_seconds=0.01,
    )
    gateway = AnonymousTwitchIRCGateway(config=config)
    connected = asyncio.Event()
    never_returns = asyncio.Event()
    attempts = 0

    class FakeReader:
        def at_eof(self) -> bool:
            return False

        async def readline(self) -> bytes:
            await never_returns.wait()
            return b""

    class FakeWriter:
        def write(self, data: bytes) -> None:
            _ = data
            return

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def fake_open_connection(*args, **kwargs):
        nonlocal attempts
        _ = args, kwargs
        attempts += 1
        if attempts == 1:
            raise OSError("temporary DNS failure")
        connected.set()
        return FakeReader(), FakeWriter()

    monkeypatch.setattr("src.gateways.twitch_irc.asyncio.open_connection", fake_open_connection)

    task = asyncio.create_task(gateway.start())
    await asyncio.wait_for(connected.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert attempts == 2


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
    gateway._reader = _reader(SimpleNamespace(at_eof=lambda: False))
    gateway._writer = _writer(SimpleNamespace(is_closing=lambda: False))
    gateway._read_task = _read_task(loop.create_future())
    gateway._read_task.set_result(None)
    _bind_send_line_with_reconnect(gateway, fake_send_line)
    gateway.ensure_connected = fake_ensure_connected

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

    async def fake_open_connection(*_args, **_kwargs):
        return FakeReader(), FakeWriter()

    monkeypatch.setattr("src.gateways.twitch_irc.asyncio.open_connection", fake_open_connection)

    await gateway._open_connection()

    assert sent_lines[0] == "PASS SCHMOOPIIE"
    assert sent_lines[1].startswith("CAP REQ :twitch.tv/tags twitch.tv/commands")
