"""Twitch IRC entrypoint for normalized chat intake."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from src.events.event_types import TwitchChatMessageEvent
from src.gateways.twitch_irc import AnonymousTwitchIRCGateway
from src.services.chat_pipeline import ChatMessageProcessingService

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
    """Parse a raw IRC line into its structured components."""
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


class TwitchIRCEntrypoint:
    """Consume raw IRC lines and forward normalized chat messages into the pipeline."""

    def __init__(
        self,
        gateway: AnonymousTwitchIRCGateway,
        *,
        message_processor: ChatMessageProcessingService | None = None,
    ) -> None:
        self._gateway = gateway
        self._message_processor = message_processor
        self._gateway.set_line_handler(self.handle_line)

    async def start(self) -> None:
        """Start the IRC gateway and consume incoming lines."""
        await self._gateway.start()

    async def stop(self) -> None:
        """Stop the underlying IRC gateway."""
        await self._gateway.stop()

    def set_message_processor(self, message_processor: ChatMessageProcessingService) -> None:
        """Bind the direct chat pipeline after runtime assembly."""
        self._message_processor = message_processor

    async def handle_line(self, raw_line: str) -> None:
        """Handle one raw IRC line."""
        message = parse_irc_message(raw_line)
        logger.debug("Received IRC line: %s", raw_line.strip())
        if message.command == "PING" and message.trailing:
            await self._gateway.send_pong(message.trailing)
            return

        event = build_chat_message_event(message)
        if event is None:
            return
        logger.debug(
            "Built Twitch chat event channel=%s author=%s broadcaster_id=%s message_id=%s content=%r",
            event.channel_login,
            event.author_login,
            event.broadcaster_id,
            event.message_id,
            event.content,
        )
        if self._message_processor is None:
            logger.warning("Dropping Twitch chat message because no chat pipeline is configured yet.")
            return
        await self._message_processor.process(event)


def _parse_tags(tags_part: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for item in tags_part.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            tags[key] = _decode_tag_value(value)
        else:
            tags[item] = ""
    return tags


def _decode_tag_value(value: str) -> str:
    decoded = value.replace(r"\s", " ")
    decoded = decoded.replace(r"\:", ";")
    decoded = decoded.replace(r"\\", "\\")
    decoded = decoded.replace(r"\r", "\r")
    return decoded.replace(r"\n", "\n")


def _parse_prefix_nick(prefix: str | None) -> str:
    if not prefix:
        return ""
    return prefix.split("!", 1)[0]


def _normalize_irc_chat_content(content: str) -> str:
    if content.startswith("\x01ACTION ") and content.endswith("\x01"):
        return content[8:-1]
    return content
