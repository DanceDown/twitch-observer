"""Shared account-linking helpers and runtime notification contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.events.event_types import DiscordCommandResult


class AccountNotificationSender(Protocol):
    """Deliver account-linking results back to Discord."""

    async def send_account_result(
        self,
        discord_user_id: int,
        discord_channel_id: int | None,
        result: DiscordCommandResult,
    ) -> None: ...


def format_account_timestamp(raw_value: str | None) -> str:
    """Render ISO timestamps in a shorter human-friendly form."""
    if raw_value is None:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return raw_value
    return parsed.strftime("%d-%m-%Y %H:%M:%S %Z").strip() or parsed.isoformat(sep=" ", timespec="seconds")
