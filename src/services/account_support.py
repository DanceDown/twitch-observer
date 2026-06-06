"""Shared account-linking helpers and runtime notification contracts."""

from __future__ import annotations

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
