"""Entrypoint and runtime worker assembly."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass

from src.entrypoints.discord import DiscordEntrypoint
from src.entrypoints.discord.ui_data import DiscordUIDataProvider
from src.entrypoints.twitch_irc import TwitchIRCEntrypoint
from src.services.account_polling_service import DeviceFlowPollingService
from src.services.discord_presence_service import DiscordPresenceService
from src.services.irc_bootstrap_service import IRCBootstrapService
from src.services.twitch_live_monitor_service import TwitchLiveMonitorService

from .models import ApplicationCore, ApplicationEntrypoints, ApplicationGateways, ApplicationRuntime, ApplicationServices


def build_entrypoints(
    core: ApplicationCore,
    services: ApplicationServices,
    gateways: ApplicationGateways,
) -> ApplicationEntrypoints:
    discord_entrypoint = DiscordEntrypoint(
        config=core.config,
        services=services.discord,
        ui_data_provider=DiscordUIDataProvider(queries=services.ui_queries),
        localizer=core.localizer,
    )
    services.runtime_coordinator.tracking_sender = discord_entrypoint
    services.runtime_coordinator.account_sender = discord_entrypoint
    services.runtime_coordinator.channel_result_sender = discord_entrypoint
    services.runtime_coordinator.presence_sender = discord_entrypoint
    twitch_irc_entrypoint = TwitchIRCEntrypoint(gateways.twitch_irc, message_processor=services.chat_pipeline)
    return ApplicationEntrypoints(twitch_irc=twitch_irc_entrypoint, discord=discord_entrypoint)


def build_runtime(
    core: ApplicationCore, services: ApplicationServices, gateways: ApplicationGateways, entrypoints: ApplicationEntrypoints
) -> ApplicationRuntime:
    live_monitor_service = TwitchLiveMonitorService(
        channel_repository=core.channel_repository,
        twitch_api=core.twitch_bundle,
        poll_interval_seconds=core.config.twitch_live_monitor_poll_interval_seconds,
        batch_size=core.config.twitch_live_monitor_batch_size,
        refresh_on_startup=core.config.twitch_live_monitor_refresh_on_startup,
        on_change=services.live_state_orchestrator.handle_change,
    )
    services.runtime_coordinator.tracked_channels_notifier = _LiveMonitorTrackedChannelsNotifier(live_monitor_service)

    irc_bootstrap_service = IRCBootstrapService(
        channel_repository=core.channel_repository,
        twitch_api=core.twitch_bundle,
        irc_gateway=gateways.twitch_irc,
        connect_timeout_seconds=core.config.irc_bootstrap_connect_timeout_seconds,
        resync_interval_seconds=core.config.irc_channel_resync_interval_seconds,
    )
    device_flow_poller = DeviceFlowPollingService(
        device_flow_repository=core.device_flow_repository,
        account_repository=core.account_repository,
        thread_repository=core.thread_repository,
        twitch_api=core.twitch_bundle,
        notifier=entrypoints.discord,
        poll_interval_seconds=core.config.twitch_device_flow_poll_interval_seconds,
        localizer=core.localizer,
    )
    presence_service = DiscordPresenceService(
        message_repository=core.message_repository,
        notifier=entrypoints.discord,
        poll_interval_seconds=core.config.discord_presence_poll_interval_seconds,
        lookback_minutes=core.config.discord_presence_lookback_minutes,
        message_limit=core.config.discord_presence_message_limit,
        max_status_length=core.config.discord_presence_max_status_length,
    )
    return ApplicationRuntime(
        live_monitor_service=live_monitor_service,
        irc_bootstrap_service=irc_bootstrap_service,
        device_flow_poller=device_flow_poller,
        presence_service=presence_service,
        twitch_irc_task=asyncio.create_task(entrypoints.twitch_irc.start(), name="twitch-irc-entrypoint"),
        discord_task=asyncio.create_task(entrypoints.discord.start(), name="discord-entrypoint"),
    )


@dataclass(slots=True)
class _LiveMonitorTrackedChannelsNotifier:
    monitor: TwitchLiveMonitorService

    async def notify_tracked_channels_changed(self) -> None:
        self.monitor.notify_tracked_channels_changed()


async def start_runtime(runtime: ApplicationRuntime) -> None:
    await runtime.live_monitor_service.start()
    await runtime.irc_bootstrap_service.sync_persisted_channels()
    await runtime.irc_bootstrap_service.start_periodic_sync()
    await runtime.device_flow_poller.start()
    await runtime.presence_service.start()


async def stop_runtime(core: ApplicationCore, entrypoints: ApplicationEntrypoints, runtime: ApplicationRuntime) -> None:
    runtime.twitch_irc_task.cancel()
    runtime.discord_task.cancel()
    with suppress(asyncio.CancelledError):
        await runtime.twitch_irc_task
    with suppress(asyncio.CancelledError):
        await runtime.discord_task
    await runtime.live_monitor_service.stop()
    await runtime.irc_bootstrap_service.stop_periodic_sync()
    await runtime.device_flow_poller.stop()
    await runtime.presence_service.stop()
    await core.twitch_bundle.close()
    await entrypoints.discord.stop()
    await entrypoints.twitch_irc.stop()
    core.database.close()

