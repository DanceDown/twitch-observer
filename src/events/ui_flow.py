"""Discord UI flow models and typed steps."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .discord_results import DiscordCommandResult


class UIFlowKind(StrEnum):
    """Top-level Discord UI flows."""

    THREAD = "thread"
    CHANNEL = "channel"
    USER = "user"
    SHOW = "show"
    PERMISSION = "permission"
    ACCOUNT = "account"
    LIVE = "live"
    WRITE = "write"
    PATTERN = "ping"
    REPLY = "reply"


class UIFlowStep(StrEnum):
    """Typed Discord UI flow steps."""

    ROOT = "root"
    REMOVE = "remove"
    LEAVE = "leave"
    COLOR = "color"
    ADD_PATTERN = "add_pattern"
    ADD_EVENT = "add_event"
    ENABLE = "enable"
    DISABLE = "disable"


@dataclass(slots=True, frozen=True)
class DiscordUIFlowDecision:
    """Decision for opening the next Discord UI step."""

    flow: UIFlowKind
    step: UIFlowStep
    open_ui: bool
    result: DiscordCommandResult | None = None


@dataclass(slots=True, frozen=True)
class RequestUIFlowCommand:
    """Request a service-owned decision before opening a Discord UI step."""

    discord_channel_id: int | None
    requester_id: int
    flow: UIFlowKind
    step: UIFlowStep
