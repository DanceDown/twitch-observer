"""Parse Twitch IRC lines and build normalized chat events."""

from __future__ import annotations

from datetime import UTC, datetime

from src.events.twitch_events import TwitchChatMessageEvent

from .models import IRCMessage


class InvalidIRCLineError(ValueError):
    """Raised when a raw line cannot be parsed as an IRC message."""

    def __init__(self, raw_line: str) -> None:
        """Create a parse error that includes the raw IRC line."""
        super().__init__(f"Invalid IRC line: {raw_line!r}")


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
        raise InvalidIRCLineError(raw_line)

    command = parts[0]
    params = parts[1:]
    return IRCMessage(tags=tags, prefix=prefix, command=command, params=params, trailing=trailing, raw=raw_line.strip())


def build_chat_message_event(message: IRCMessage) -> TwitchChatMessageEvent | None:
    """Convert supported Twitch IRC message types into the app's normalized chat event."""
    if not message.params:
        return None

    if message.command == "PRIVMSG":
        return _build_privmsg_event(message)
    if message.command == "USERNOTICE":
        return _build_usernotice_event(message)
    return None


def _build_privmsg_event(message: IRCMessage) -> TwitchChatMessageEvent | None:
    if message.trailing is None:
        return None

    normalized_content = _normalize_irc_chat_content(message.trailing)
    return TwitchChatMessageEvent(
        channel_login=_parse_channel_login(message.params[0]),
        author_login=_parse_prefix_nick(message.prefix),
        author_display_name=(message.tags.get("display-name") or _parse_prefix_nick(message.prefix)),
        content=normalized_content,
        message_id=message.tags.get("id"),
        broadcaster_id=message.tags.get("room-id"),
        author_id=message.tags.get("user-id"),
        color=message.tags.get("color") or None,
        reply_parent_message_id=message.tags.get("reply-parent-msg-id"),
        message_kind=_resolve_privmsg_kind(message.trailing),
        sent_at=_parse_sent_at(message.tags.get("tmi-sent-ts")),
        raw_line=message.raw,
        raw_tags=message.tags,
    )


def _build_usernotice_event(message: IRCMessage) -> TwitchChatMessageEvent:
    author_login = (message.tags.get("login") or _parse_prefix_nick(message.prefix)).lower()
    display_name = message.tags.get("display-name") or author_login
    user_text = None if message.trailing is None else _normalize_irc_chat_content(message.trailing)
    system_message = message.tags.get("system-msg") or None

    return TwitchChatMessageEvent(
        channel_login=_parse_channel_login(message.params[0]),
        author_login=author_login,
        author_display_name=display_name,
        content=_build_usernotice_content(system_message=system_message, user_text=user_text),
        message_id=message.tags.get("id"),
        broadcaster_id=message.tags.get("room-id"),
        author_id=message.tags.get("user-id"),
        color=message.tags.get("color") or None,
        message_kind="usernotice",
        notice_type=message.tags.get("msg-id") or None,
        system_message=system_message,
        sent_at=_parse_sent_at(message.tags.get("tmi-sent-ts")),
        raw_line=message.raw,
        raw_tags=message.tags,
    )


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
    return prefix.split("!", 1)[0].lower()


def _parse_channel_login(channel_param: str) -> str:
    return channel_param.lstrip("#").lower()


def _parse_sent_at(timestamp_ms: str | None) -> datetime:
    if timestamp_ms and timestamp_ms.isdigit():
        return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=UTC)
    return datetime.now(UTC)


def _normalize_irc_chat_content(content: str) -> str:
    if content.startswith("\x01ACTION ") and content.endswith("\x01"):
        return content[8:-1]
    return content


def _resolve_privmsg_kind(content: str) -> str:
    if content.startswith("\x01ACTION ") and content.endswith("\x01"):
        return "action"
    return "privmsg"


def _build_usernotice_content(*, system_message: str | None, user_text: str | None) -> str:
    parts = [part for part in (system_message, user_text) if part]
    if not parts:
        return ""
    return "\n\n".join(parts)
