"""Discord-facing result models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DiscordResultStyle(StrEnum):
    """Presentation style for Discord embeds."""

    SUCCESS = "success"
    ERROR = "error"
    INFO = "info"


@dataclass(slots=True, frozen=True)
class DiscordCommandResult:
    """Result of a Discord-triggered command handling pipeline."""

    title: str
    message: str
    footer: str = ""
    style: DiscordResultStyle = DiscordResultStyle.INFO
    ephemeral: bool = False
    thumbnail_url: str | None = None
    color: str | None = None
    language: str | None = None
