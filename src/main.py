from __future__ import annotations

"""Application entry point wiring adapters, services and persistence together."""

import asyncio
import logging
import signal
from contextlib import suppress

from src.adapters.discord import DiscordAdapter
from src.adapters.twitch_api import TwitchAPIClient
from src.adapters.twitch_irc import AnonymousTwitchIRCAdapter
from src.config import AppConfig
from src.database.connection import (
    PostgresChannelRepository,
    PostgresDatabase,
    PostgresMessageRepository,
    PostgresPatternRepository,
    PostgresReplyRepository,
    PostgresThreadRepository,
    PostgresTwitchAccountRepository,
    PostgresTwitchDeviceFlowRepository,
    PostgresUserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.services.account_service import AccountCommandService, DeviceFlowPollingService
from src.services.channel_command_service import ChannelCommandService
from src.services.message_ingest_service import MessageIngestService
from src.services.pattern_service import PatternCommandService, PatternTrackingService, ShowCommandService
from src.services.permission_service import PermissionCommandService
from src.services.reply_service import AutoReplyService, ReplyCommandService
from src.services.thread_lifecycle_service import ThreadLifecycleService
from src.services.write_service import TwitchWriteCommandService


async def _run() -> None:
    """Boot the application and keep it running until shutdown is requested."""
    config = AppConfig()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    event_bus = EventBus()
    database = PostgresDatabase(config)
    message_repository = PostgresMessageRepository(database)
    thread_repository = PostgresThreadRepository(database)
    channel_repository = PostgresChannelRepository(database)
    pattern_repository = PostgresPatternRepository(database)
    reply_repository = PostgresReplyRepository(database)
    permission_repository = PostgresUserPermissionRepository(database)
    account_repository = PostgresTwitchAccountRepository(database)
    device_flow_repository = PostgresTwitchDeviceFlowRepository(database)
    twitch_api = TwitchAPIClient(config)

    database.healthcheck()
    database.ensure_schema_compatibility()
    MessageIngestService(event_bus=event_bus, message_repository=message_repository)
    AccountCommandService(
        event_bus=event_bus,
        account_repository=account_repository,
        device_flow_repository=device_flow_repository,
        thread_repository=thread_repository,
        twitch_api=twitch_api,
        permission_repository=permission_repository,
    )

    irc_adapter = AnonymousTwitchIRCAdapter(config=config, event_bus=event_bus)
    ThreadLifecycleService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        twitch_api=twitch_api,
        irc_manager=irc_adapter,
        permission_repository=permission_repository,
    )
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_manager=irc_adapter,
        permission_repository=permission_repository,
    )
    discord_adapter = DiscordAdapter(config=config, event_bus=event_bus)
    device_flow_poller = DeviceFlowPollingService(
        device_flow_repository=device_flow_repository,
        account_repository=account_repository,
        thread_repository=thread_repository,
        twitch_api=twitch_api,
        notifier=discord_adapter,
    )
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        permission_repository=permission_repository,
    )
    PermissionCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        permission_repository=permission_repository,
    )
    ReplyCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        permission_repository=permission_repository,
    )
    ShowCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        permission_repository=permission_repository,
    )
    PatternTrackingService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        notifier=discord_adapter,
        reply_repository=reply_repository,
    )
    AutoReplyService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
        notifier=discord_adapter,
    )
    TwitchWriteCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
        permission_repository=permission_repository,
    )

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, _request_stop)

    irc_task = asyncio.create_task(irc_adapter.start(), name="twitch-irc-adapter")
    discord_task = asyncio.create_task(discord_adapter.start(), name="discord-adapter")
    await device_flow_poller.start()

    try:
        await stop_event.wait()
    finally:
        irc_task.cancel()
        discord_task.cancel()
        with suppress(asyncio.CancelledError):
            await irc_task
        with suppress(asyncio.CancelledError):
            await discord_task
        await device_flow_poller.stop()
        await twitch_api.close()
        await discord_adapter.stop()
        await irc_adapter.stop()
        database.close()


def main() -> None:
    """Start the async application runtime."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
