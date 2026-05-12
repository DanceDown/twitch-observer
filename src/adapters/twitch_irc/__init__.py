"""Anonymous Twitch IRC adapter.

This adapter is responsible only for transport and normalization:
- connect to Twitch IRC anonymously
- parse raw IRC protocol lines
- convert relevant PRIVMSG lines into domain events
- publish those events to the event bus

All business logic stays outside of this module.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime

from src.config import AppConfig
from src.events.event_bus import EventBus
from src.events.event_types import EventType, TwitchChatMessageEvent

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class IRCMessage:
    """Parsed IRC line with tags, prefix, command and payload."""

    tags: dict[str, str]
    prefix: str | None
    command: str
    params: list[str]
    trailing: str | None
    raw: str


def parse_irc_message(raw_line: str) -> IRCMessage:
    """Parse a raw IRC line into its structured components.

    Example input:
    @display-name=TestUser;id=abc123;room-id=999;user-id=777
    :testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #example :Hello world!
    """
    line = raw_line.strip("\r\n")
    tags: dict[str, str] = {}
    prefix: str | None = None

    if line.startswith("@"):
        tags_part, line = line.split(" ", 1)
        tags = _parse_tags(tags_part[1:])

    if line.startswith(":"):
        prefix_part, line = line.split(" ", 1)
        prefix = prefix_part[1:]

    if " :" in line:
        before_trailing, trailing = line.split(" :", 1)
    else:
        before_trailing, trailing = line, None

    parts = [part for part in before_trailing.split(" ") if part]
    if not parts:
        raise ValueError(f"Invalid IRC line: {raw_line!r}")

    command = parts[0]
    params = parts[1:]
    return IRCMessage(tags=tags, prefix=prefix, command=command, params=params, trailing=trailing, raw=raw_line.strip())


def build_chat_message_event(message: IRCMessage) -> TwitchChatMessageEvent | None:
    """Convert a parsed IRC PRIVMSG into the app's normalized chat event."""
    if message.command != "PRIVMSG" or not message.params or message.trailing is None:
        return None

    channel_login = message.params[0].lstrip("#").lower()
    author_login = _parse_prefix_nick(message.prefix)
    display_name = message.tags.get("display-name") or author_login
    timestamp_ms = message.tags.get("tmi-sent-ts")
    sent_at = datetime.now(UTC)
    if timestamp_ms and timestamp_ms.isdigit():
        sent_at = datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=UTC)

    normalized_content = _normalize_irc_chat_content(message.trailing)

    return TwitchChatMessageEvent(
        channel_login=channel_login,
        author_login=author_login,
        author_display_name=display_name,
        content=normalized_content,
        message_id=message.tags.get("id"),
        broadcaster_id=message.tags.get("room-id"),
        author_id=message.tags.get("user-id"),
        color=message.tags.get("color") or None,
        reply_parent_message_id=message.tags.get("reply-parent-msg-id"),
        sent_at=sent_at,
        raw_line=message.raw,
        raw_tags=message.tags,
    )


class AnonymousTwitchIRCAdapter:
    """Read Twitch chat anonymously over IRC and publish normalized events."""

    def __init__(self, config: AppConfig, event_bus: EventBus) -> None:
        self._config = config
        self._event_bus = event_bus
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._nick = self._build_anonymous_nick(config.twitch_irc_nick_prefix)
        self._joined_channels: set[str] = set()
        self._pending_channels: set[str] = set()
        self._connected_event = asyncio.Event()
        self._connection_lock = asyncio.Lock()
        self._read_task: asyncio.Task[None] | None = None
        self._stop_requested = False

    @property
    def nick(self) -> str:
        return self._nick

    async def start(self) -> None:
        """Keep the IRC connection alive, rejoining channels after reconnects.

        The adapter connects even if no channels are configured yet. This allows
        the application to stay ready for channels that may be added later
        through Discord commands or other configuration flows.
        """
        self._stop_requested = False
        await self.ensure_connected()
        self._ensure_read_task()

        try:
            while not self._stop_requested:
                await asyncio.sleep(self._config.twitch_irc_connection_check_interval_seconds)
                if self._read_task is not None and self._read_task.done():
                    await self._recover_connection("read loop stopped")
                    continue
                if not self._is_transport_connected():
                    await self._recover_connection("connection health check failed")
        finally:
            self._stop_requested = True
            await self._stop_read_task()
            await self._close_connection(preserve_channels=True)

    async def stop(self) -> None:
        """Close the IRC writer and reset the adapter state."""
        self._stop_requested = True
        await self._stop_read_task()
        await self._close_connection(preserve_channels=False)
        self._joined_channels.clear()
        self._pending_channels.clear()

    async def handle_line(self, raw_line: str) -> None:
        """Handle one raw IRC line.

        PING messages are answered immediately. PRIVMSG lines are normalized and
        forwarded as domain events.
        """
        message = parse_irc_message(raw_line)
        logger.debug("Received IRC line: %s", raw_line.strip())
        if message.command == "PING" and message.trailing:
            await self._send_line(f"PONG :{message.trailing}")
            return

        event = build_chat_message_event(message)
        if event is not None:
            logger.debug(
                "Built Twitch chat event channel=%s author=%s broadcaster_id=%s message_id=%s content=%r",
                event.channel_login,
                event.author_login,
                event.broadcaster_id,
                event.message_id,
                event.content,
            )
            await self._event_bus.publish(EventType.TWITCH_CHAT_MESSAGE, event)

    async def join_channel(self, channel_login: str) -> None:
        """Join one Twitch channel after normalizing and deduplicating the login."""
        normalized = channel_login.strip().lstrip("#").lower()
        if not normalized or normalized in self._joined_channels:
            return
        if not self._is_connection_ready():
            logger.warning("Twitch IRC was disconnected before joining #%s; reconnecting.", normalized)
        await self.ensure_connected()
        if normalized in self._joined_channels:
            return
        await self._send_line_with_reconnect(f"JOIN #{normalized}")
        self._pending_channels.discard(normalized)
        self._joined_channels.add(normalized)
        logger.debug("Joined Twitch IRC channel #%s", normalized)

    async def join_channels(self, channel_logins: list[str]) -> None:
        """Join multiple Twitch channels."""
        for channel_login in channel_logins:
            await self.join_channel(channel_login)

    async def leave_channel(self, channel_login: str) -> None:
        """Leave one Twitch channel after normalizing the login."""
        normalized = channel_login.strip().lstrip("#").lower()
        if not normalized:
            return
        if normalized not in self._joined_channels and normalized not in self._pending_channels:
            return
        if not self._is_connection_ready():
            logger.warning("Twitch IRC was disconnected before parting #%s; reconnecting.", normalized)
        await self.ensure_connected()
        await self._send_line_with_reconnect(f"PART #{normalized}")
        self._pending_channels.discard(normalized)
        self._joined_channels.discard(normalized)
        logger.debug("Left Twitch IRC channel #%s", normalized)

    async def wait_until_connected(self) -> None:
        """Wait until the IRC connection is established and handshake lines were sent."""
        await self.ensure_connected()
        await self._connected_event.wait()

    async def _read_loop(self) -> None:
        """Continuously read raw lines from the IRC socket."""
        reader = self._reader
        assert reader is not None
        while not reader.at_eof():
            raw_bytes = await reader.readline()
            if not raw_bytes:
                break
            raw_line = raw_bytes.decode("utf-8", errors="replace")
            try:
                await self.handle_line(raw_line)
            except Exception:
                logger.exception("Failed to handle Twitch IRC line; continuing read loop. raw_line=%r", raw_line)

    async def _send_line(self, line: str) -> None:
        """Send one IRC command line to the server."""
        if self._writer is None:
            raise ConnectionError("Twitch IRC connection is not available.")
        logger.debug("Sending IRC line: %s", line)
        self._writer.write(f"{line}\r\n".encode())
        await self._writer.drain()

    async def ensure_connected(self) -> None:
        """Reconnect immediately when the IRC transport is no longer healthy."""
        if self._is_connection_ready():
            return
        async with self._connection_lock:
            if self._is_connection_ready():
                return
            await self._stop_read_task()
            await self._close_connection(preserve_channels=True)
            await self._open_connection()
            self._ensure_read_task()

    async def _open_connection(self) -> None:
        ssl_context = ssl.create_default_context() if self._config.twitch_irc_use_ssl else None
        self._reader, self._writer = await asyncio.open_connection(
            self._config.twitch_irc_host,
            self._config.twitch_irc_port,
            ssl=ssl_context,
        )
        logger.debug("Connected to Twitch IRC at %s:%s", self._config.twitch_irc_host, self._config.twitch_irc_port)
        await self._send_line("PASS SCHMOOPIIE")
        await self._send_line("CAP REQ :twitch.tv/tags twitch.tv/commands")
        await self._send_line(f"NICK {self._nick}")
        await self._send_line(f"USER {self._nick} 8 * :{self._nick}")
        self._connected_event.set()
        await self._join_initial_channels()

    async def _join_initial_channels(self) -> None:
        initial_channels = set(self._config.twitch_irc_channels) | self._pending_channels
        if not initial_channels:
            print("No Twitch IRC channels configured yet; connection is ready for later joins.")
            return
        self._pending_channels.clear()
        for channel_login in sorted(initial_channels):
            normalized = channel_login.strip().lstrip("#").lower()
            if not normalized or normalized in self._joined_channels:
                continue
            await self._send_line(f"JOIN #{normalized}")
            self._joined_channels.add(normalized)
            logger.debug("Joined Twitch IRC channel #%s", normalized)

    async def _send_line_with_reconnect(self, line: str) -> None:
        try:
            await self._send_line(line)
        except (ConnectionError, OSError) as error:
            logger.warning("IRC command failed (%s); reconnecting and retrying: %s", error, line)
            await self._recover_connection("command send failed")
            await self._send_line(line)

    async def _recover_connection(self, reason: str) -> None:
        logger.warning("Twitch IRC connection lost (%s). Reconnecting.", reason)
        await self._stop_read_task()
        await self._close_connection(preserve_channels=True)
        await self.ensure_connected()

    async def _close_connection(self, *, preserve_channels: bool) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        self._connected_event.clear()
        if preserve_channels:
            self._pending_channels.update(self._joined_channels)
        self._joined_channels.clear()
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def _ensure_read_task(self) -> None:
        if self._stop_requested:
            return
        if self._read_task is not None and not self._read_task.done():
            return
        self._read_task = asyncio.create_task(self._read_loop(), name="twitch-irc-read-loop")

    async def _stop_read_task(self) -> None:
        task = self._read_task
        self._read_task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def _is_connection_ready(self) -> bool:
        return self._is_transport_connected() and not (self._read_task is not None and self._read_task.done())

    def _is_transport_connected(self) -> bool:
        if self._reader is None or self._writer is None:
            return False
        if self._reader.at_eof():
            return False
        is_closing = getattr(self._writer, "is_closing", None)
        if callable(is_closing) and is_closing():
            return False
        return True

    @staticmethod
    def _build_anonymous_nick(prefix: str) -> str:
        """Build a Twitch-compatible anonymous nick such as justinfan12345."""
        return f"{prefix}{random.randint(10000, 999999)}"


def _parse_tags(tags_part: str) -> dict[str, str]:
    """Parse Twitch IRC tags from the key=value;key=value format."""
    tags: dict[str, str] = {}
    for item in tags_part.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            tags[key] = _decode_tag_value(value)
        else:
            tags[item] = ""
    return tags


def _decode_tag_value(value: str) -> str:
    """Decode escaped IRC tag values used by Twitch."""
    decoded = value.replace(r"\s", " ")
    decoded = decoded.replace(r"\:", ";")
    decoded = decoded.replace(r"\\", "\\")
    decoded = decoded.replace(r"\r", "\r")
    return decoded.replace(r"\n", "\n")


def _parse_prefix_nick(prefix: str | None) -> str:
    """Extract the nick from an IRC prefix such as user!user@host."""
    if not prefix:
        return ""
    return prefix.split("!", 1)[0]


def _normalize_irc_chat_content(content: str) -> str:
    """Normalize IRC chat payloads such as CTCP ACTION into plain chat text."""
    if content.startswith("\x01ACTION ") and content.endswith("\x01"):
        return content[8:-1]
    return content

