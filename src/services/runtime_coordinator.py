"""Application runtime coordinator for cross-runtime side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import discord

from src.events.discord_results import DiscordCommandResult
from src.services.account_support import AccountNotificationSender
from src.services.channel_event_notification_service import ChannelEventNotificationSender
from src.services.discord_presence_service import DiscordPresenceStatusSender
from src.services.patterns import TrackingNotificationSender


class TrackedChannelsChangedNotifier:
    """Notify runtime workers that tracked channels changed."""

    async def notify_tracked_channels_changed(self) -> None:  # pragma: no cover
        """Wake workers that need to resync tracked Twitch channels."""
        raise NotImplementedError


@dataclass(slots=True)
class TrackingRuntimeRelay(TrackingNotificationSender):
    """Late-bound tracking notification relay."""

    sender: TrackingNotificationSender | None = None

    def bind(self, sender: TrackingNotificationSender) -> None:
        """Attach the concrete Discord tracking sender once it exists."""
        self.sender = sender

    async def reserve_tracking_delivery(self, *, thread_id: int) -> None:
        """Reserve an ordered tracking-delivery slot if a sender is bound."""
        if self.sender is None:
            return
        await self.sender.reserve_tracking_delivery(thread_id=thread_id)

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        """Forward a prepared tracking embed if a sender is bound."""
        if self.sender is None:
            return
        await self.sender.send_tracking_embed(
            discord_channel_id,
            embed,
            channel_login=channel_login,
            thread_id=thread_id,
        )


@dataclass(slots=True)
class AccountRuntimeRelay(AccountNotificationSender):
    """Late-bound account result relay."""

    sender: AccountNotificationSender | None = None

    def bind(self, sender: AccountNotificationSender) -> None:
        """Attach the concrete Discord account-result sender once it exists."""
        self.sender = sender

    async def send_account_result(
        self,
        discord_user_id: int,
        discord_channel_id: int | None,
        result: DiscordCommandResult,
    ) -> None:
        """Forward an account-linking result if a sender is bound."""
        if self.sender is None:
            return
        await self.sender.send_account_result(discord_user_id, discord_channel_id, result)


@dataclass(slots=True)
class ChannelResultRuntimeRelay(ChannelEventNotificationSender):
    """Late-bound channel-event notification relay."""

    sender: ChannelEventNotificationSender | None = None

    def bind(self, sender: ChannelEventNotificationSender) -> None:
        """Attach the concrete Discord channel-event sender once it exists."""
        self.sender = sender

    async def send_channel_result(
        self,
        discord_channel_id: int,
        result: DiscordCommandResult,
    ) -> None:
        """Forward a channel-event result if a sender is bound."""
        if self.sender is None:
            return
        await self.sender.send_channel_result(discord_channel_id, result)


@dataclass(slots=True)
class PresenceRuntimeRelay(DiscordPresenceStatusSender):
    """Late-bound Discord presence relay."""

    sender: DiscordPresenceStatusSender | None = None

    def bind(self, sender: DiscordPresenceStatusSender) -> None:
        """Attach the concrete Discord presence sender once it exists."""
        self.sender = sender

    async def set_status_text(self, text: str) -> None:
        """Forward a Discord presence update if a sender is bound."""
        if self.sender is None:
            return
        await self.sender.set_status_text(text)


@dataclass(slots=True)
class TrackedChannelsRuntimeRelay(TrackedChannelsChangedNotifier):
    """Late-bound tracked-channel wake-up relay."""

    notifier: TrackedChannelsChangedNotifier | None = None

    def bind(self, notifier: TrackedChannelsChangedNotifier) -> None:
        """Attach the live-monitor wake-up notifier once it exists."""
        self.notifier = notifier

    async def notify_tracked_channels_changed(self) -> None:
        """Wake the tracked-channel monitor if a notifier is bound."""
        if self.notifier is None:
            return
        await self.notifier.notify_tracked_channels_changed()


class DiscordRuntimeSender(Protocol):
    """Combined Discord-side runtime sender contract."""

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        """Send one tracking embed to a Discord destination."""
        ...

    async def send_account_result(
        self,
        discord_user_id: int,
        discord_channel_id: int | None,
        result: DiscordCommandResult,
    ) -> None:
        """Send one account-linking result to Discord."""
        ...

    async def send_channel_result(self, discord_channel_id: int, result: DiscordCommandResult) -> None:
        """Send one channel-event notification result to Discord."""
        ...

    async def set_status_text(self, text: str) -> None:
        """Set the bot's Discord presence text."""
        ...


@dataclass(slots=True)
class ApplicationRuntimeCoordinator:
    """Own the small late-bound runtime relays used by services and workers."""

    tracking: TrackingRuntimeRelay = field(default_factory=TrackingRuntimeRelay)
    accounts: AccountRuntimeRelay = field(default_factory=AccountRuntimeRelay)
    channel_results: ChannelResultRuntimeRelay = field(default_factory=ChannelResultRuntimeRelay)
    presence: PresenceRuntimeRelay = field(default_factory=PresenceRuntimeRelay)
    tracked_channels: TrackedChannelsRuntimeRelay = field(default_factory=TrackedChannelsRuntimeRelay)

    def bind_discord(self, sender: DiscordRuntimeSender) -> None:
        """Bind all Discord-facing relays to one concrete runtime sender."""
        self.tracking.bind(sender)
        self.accounts.bind(sender)
        self.channel_results.bind(sender)
        self.presence.bind(sender)

    def bind_tracked_channels_notifier(self, notifier: TrackedChannelsChangedNotifier) -> None:
        """Bind the notifier used when tracked channel configuration changes."""
        self.tracked_channels.bind(notifier)
