"""Data models for parsed Twitch IRC lines."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class IRCMessage:
    """Parsed IRC line with tags, prefix, command and payload."""

    tags: dict[str, str]
    prefix: str | None
    command: str
    params: list[str]
    trailing: str | None
    raw: str
