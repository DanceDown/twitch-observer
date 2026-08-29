"""Anonymous Twitch IRC network gateway."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import ssl
from collections.abc import Awaitable, Callable

from src.config import AppConfig

logger = logging.getLogger(__name__)


class AnonymousTwitchIRCGateway:
    """Manage the anonymous Twitch IRC connection and channel membership."""

    def __init__(
        self,
        config: AppConfig,
        *,
        line_handler: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._line_handler = line_handler
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

    def set_line_handler(self, line_handler: Callable[[str], Awaitable[None]]) -> None:
        """Bind the raw IRC line handler used by the entrypoint."""
        self._line_handler = line_handler

    async def start(self) -> None:
        """Keep the IRC connection alive, rejoining channels after reconnects."""
        self._stop_requested = False
        reconnect_delay = max(0.1, self._config.twitch_irc_reconnect_initial_delay_seconds)
        max_reconnect_delay = max(reconnect_delay, self._config.twitch_irc_reconnect_max_delay_seconds)

        try:
            while not self._stop_requested:
                try:
                    await self.ensure_connected()
                    self._ensure_read_task()
                    reconnect_delay = max(0.1, self._config.twitch_irc_reconnect_initial_delay_seconds)
                    await asyncio.sleep(self._config.twitch_irc_connection_check_interval_seconds)
                    if self._read_task is not None and self._read_task.done():
                        await self._recover_connection("read loop stopped")
                        continue
                    if not self._is_transport_connected():
                        await self._recover_connection("connection health check failed")
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning(
                        "Twitch IRC connection loop recovered from error; retrying in %.1fs: %s",
                        reconnect_delay,
                        error,
                        exc_info=True,
                    )
                    await self._stop_read_task()
                    await self._close_connection(preserve_channels=True)
                    await self._sleep_until_retry(reconnect_delay)
                    reconnect_delay = min(max_reconnect_delay, reconnect_delay * 2)
        finally:
            self._stop_requested = True
            await self._stop_read_task()
            await self._close_connection(preserve_channels=True)

    async def stop(self) -> None:
        """Close the IRC writer and reset the gateway state."""
        self._stop_requested = True
        await self._stop_read_task()
        await self._close_connection(preserve_channels=False)
        self._joined_channels.clear()
        self._pending_channels.clear()

    async def join_channel(self, channel_login: str) -> None:
        """Join one Twitch channel after normalizing and deduplicating the login."""
        normalized = channel_login.strip().lstrip("#").lower()
        if not normalized or normalized in self._joined_channels:
            return
        if not self._is_connection_ready():
            logger.warning("Twitch IRC was disconnected before joining #%s; reconnecting.", normalized)
        self._pending_channels.add(normalized)
        await self.ensure_connected()
        if normalized in self._joined_channels:
            self._pending_channels.discard(normalized)
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

    async def send_pong(self, payload: str) -> None:
        """Answer one Twitch IRC PING payload."""
        await self._send_line(f"PONG :{payload}")

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

    async def _read_loop(self) -> None:
        reader = self._reader
        if reader is None:
            raise RuntimeError("Twitch IRC read loop started without an active reader.")
        while not reader.at_eof():
            try:
                raw_bytes = await reader.readline()
            except OSError as error:
                logger.warning("Twitch IRC read loop stopped after connection error: %s", error)
                break
            if not raw_bytes:
                break
            raw_line = raw_bytes.decode("utf-8", errors="replace")
            ping_payload = self._extract_ping_payload(raw_line)
            if ping_payload is not None:
                try:
                    await self.send_pong(ping_payload)
                except (ConnectionError, OSError) as error:
                    logger.warning("Twitch IRC read loop stopped after PING/PONG connection error: %s", error)
                    break
                continue
            try:
                if self._line_handler is not None:
                    await self._line_handler(raw_line)
            except (ConnectionError, OSError) as error:
                logger.warning("Twitch IRC read loop stopped after line handling connection error: %s", error)
                break
            except Exception:
                logger.exception("Failed to handle Twitch IRC line; continuing read loop. raw_line=%r", raw_line)

    @staticmethod
    def _extract_ping_payload(raw_line: str) -> str | None:
        line = raw_line.strip()
        if not line.startswith("PING "):
            return None
        return line.removeprefix("PING ").removeprefix(":").strip()

    async def _send_line(self, line: str) -> None:
        if self._writer is None:
            raise ConnectionError("Twitch IRC connection is not available.")
        logger.debug("Sending IRC line: %s", line)
        self._writer.write(f"{line}\r\n".encode())
        await self._writer.drain()

    async def _open_connection(self) -> None:
        ssl_context = ssl.create_default_context() if self._config.twitch_irc_use_ssl else None
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.open_connection(
                self._config.twitch_irc_host,
                self._config.twitch_irc_port,
                ssl=ssl_context,
            )
            self._reader = reader
            self._writer = writer
            logger.debug("Connected to Twitch IRC at %s:%s", self._config.twitch_irc_host, self._config.twitch_irc_port)
            await self._send_line("PASS SCHMOOPIIE")
            await self._send_line("CAP REQ :twitch.tv/tags twitch.tv/commands")
            await self._send_line(f"NICK {self._nick}")
            await self._send_line(f"USER {self._nick} 8 * :{self._nick}")
            self._connected_event.set()
            await self._join_initial_channels()
        except Exception:
            self._reader = None
            self._writer = None
            self._connected_event.clear()
            if writer is not None:
                with contextlib.suppress(OSError):
                    writer.close()
                    await writer.wait_closed()
            raise

    async def _join_initial_channels(self) -> None:
        initial_channels = {
            normalized
            for channel_login in set(self._config.twitch_irc_channels) | self._pending_channels
            if (normalized := channel_login.strip().lstrip("#").lower())
        }
        if not initial_channels:
            logger.debug(
                "No initial Twitch IRC channels configured in runtime state; persisted channel subscriptions can still be rejoined by startup sync."
            )
            return
        self._pending_channels.update(initial_channels)
        for channel_login in sorted(initial_channels):
            normalized = channel_login.strip().lstrip("#").lower()
            if not normalized:
                continue
            if normalized in self._joined_channels:
                self._pending_channels.discard(normalized)
                continue
            await self._send_line(f"JOIN #{normalized}")
            self._joined_channels.add(normalized)
            self._pending_channels.discard(normalized)
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

    async def _sleep_until_retry(self, delay_seconds: float) -> None:
        await asyncio.sleep(max(0.1, delay_seconds))

    async def _close_connection(self, *, preserve_channels: bool) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        self._connected_event.clear()
        if preserve_channels:
            self._pending_channels.update(self._joined_channels)
        self._joined_channels.clear()
        if writer is not None:
            with contextlib.suppress(OSError):
                writer.close()
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
        with contextlib.suppress(asyncio.CancelledError, OSError):
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
