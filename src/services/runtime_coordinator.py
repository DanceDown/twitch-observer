"""Application runtime coordinator for cross-runtime side effects."""

from __future__ import annotations

from dataclasses import dataclass

import discord

from src.events.event_types import DiscordCommandResult
from src.services.account_service import AccountNotificationSender
from src.services.channel_event_notification_service import ChannelEventNotificationSender
from src.services.discord_presence_service import DiscordPresenceStatusSender
from src.services.patterns import TrackingNotificationSender


class TrackedChannelsChangedNotifier:
    """Notify runtime workers that tracked channels changed."""

    async def notify_tracked_channels_changed(self) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass(slots=True)
class ApplicationRuntimeCoordinator(
    TrackingNotificationSender,
    AccountNotificationSender,
    ChannelEventNotificationSender,
    DiscordPresenceStatusSender,
    TrackedChannelsChangedNotifier,
):
    """No-op by default, later bound to concrete runtime adapters."""

    tracking_sender: TrackingNotificationSender | None = None
    account_sender: AccountNotificationSender | None = None
    channel_result_sender: ChannelEventNotificationSender | None = None
    presence_sender: DiscordPresenceStatusSender | None = None
    tracked_channels_notifier: TrackedChannelsChangedNotifier | None = None

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
    ) -> None:
        if self.tracking_sender is None:
            return
        await self.tracking_sender.send_tracking_embed(
            discord_channel_id,
            embed,
            channel_login=channel_login,
        )

    async def send_account_result(
        self,
        discord_user_id: int,
        discord_channel_id: int | None,
        result: DiscordCommandResult,
    ) -> None:
        if self.account_sender is None:
            return
        await self.account_sender.send_account_result(discord_user_id, discord_channel_id, result)

    async def send_channel_result(self, discord_channel_id: int, result: DiscordCommandResult) -> None:
        if self.channel_result_sender is None:
            return
        await self.channel_result_sender.send_channel_result(discord_channel_id, result)

    async def set_status_text(self, text: str) -> None:
        if self.presence_sender is None:
            return
        await self.presence_sender.set_status_text(text)

    async def notify_tracked_channels_changed(self) -> None:
        if self.tracked_channels_notifier is None:
            return
        await self.tracked_channels_notifier.notify_tracked_channels_changed()

