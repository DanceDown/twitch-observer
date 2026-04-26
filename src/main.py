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
    PostgresAdapterEventActionRepository,
    PostgresAdapterEventRepository,
    PostgresChannelRepository,
    PostgresDatabase,
    PostgresMessageRepository,
    PostgresPatternRepository,
    PostgresReplyRepository,
    PostgresThreadRepository,
    PostgresTrackedUserRepository,
    PostgresTwitchAccountRepository,
    PostgresTwitchDeviceFlowRepository,
    PostgresTwitchUserCacheRepository,
    PostgresUserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.localization import Localizer
from src.services.account_service import AccountCommandService, DeviceFlowPollingService
from src.services.channel_command_service import ChannelCommandService
from src.services.channel_live_state_service import (
    ChannelEventCommandService,
    ChannelEventNotificationService,
    ChannelLiveStatePersistenceService,
)
from src.services.discord_presence_service import DiscordPresenceService
from src.services.irc_bootstrap_service import IRCBootstrapService
from src.services.message_ingest_service import MessageIngestService
from src.services.pattern_service import PatternCommandService, PatternTrackingService, ShowCommandService
from src.services.permission_service import PermissionCommandService
from src.services.reply_service import AutoReplyService, ChannelEventAutoReplyService, ReplyCommandService
from src.services.thread_lifecycle_service import ThreadLifecycleService
from src.services.twitch_live_monitor_service import TwitchLiveMonitorService
from src.services.twitch_user_directory_service import TwitchUserDirectoryIngestService, TwitchUserDirectoryService
from src.services.ui_flow_service import DiscordUIFlowGuardService
from src.services.user_command_service import UserCommandService
from src.services.write_service import TwitchWriteCommandService


class _DiscordOptionalVoiceWarningFilter(logging.Filter):
    """Hide optional voice dependency warnings because the bot never uses voice."""

    _IGNORED_MESSAGES = (
        "PyNaCl is not installed, voice will NOT be supported",
        "davey is not installed, voice will NOT be supported",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage() not in self._IGNORED_MESSAGES


async def _run() -> None:
    """Boot the application and keep it running until shutdown is requested."""
    config = AppConfig()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("discord.client").addFilter(_DiscordOptionalVoiceWarningFilter())
    event_bus = EventBus()
    localizer = Localizer.from_directory()
    database = PostgresDatabase(config)
    message_repository = PostgresMessageRepository(database)
    thread_repository = PostgresThreadRepository(database)
    channel_repository = PostgresChannelRepository(database)
    tracked_user_repository = PostgresTrackedUserRepository(database)
    pattern_repository = PostgresPatternRepository(database)
    reply_repository = PostgresReplyRepository(database)
    adapter_event_repository = PostgresAdapterEventRepository(database)
    adapter_event_action_repository = PostgresAdapterEventActionRepository(database)
    permission_repository = PostgresUserPermissionRepository(database)
    account_repository = PostgresTwitchAccountRepository(database)
    device_flow_repository = PostgresTwitchDeviceFlowRepository(database)
    twitch_user_cache_repository = PostgresTwitchUserCacheRepository(database)
    twitch_api = TwitchUserDirectoryService(
        twitch_api=TwitchAPIClient(config),
        repository=twitch_user_cache_repository,
        memory_cache_size=config.twitch_user_cache_memory_size,
        api_refresh_interval_seconds=config.twitch_user_cache_api_refresh_seconds,
    )

    database.healthcheck()
    database.ensure_schema_compatibility()
    MessageIngestService(event_bus=event_bus, message_repository=message_repository)
    TwitchUserDirectoryIngestService(event_bus=event_bus, directory=twitch_api)
    AccountCommandService(
        event_bus=event_bus,
        account_repository=account_repository,
        device_flow_repository=device_flow_repository,
        thread_repository=thread_repository,
        twitch_api=twitch_api,
        permission_repository=permission_repository,
        localizer=localizer,
    )

    irc_adapter = AnonymousTwitchIRCAdapter(config=config, event_bus=event_bus)
    ThreadLifecycleService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        twitch_api=twitch_api,
        irc_manager=irc_adapter,
        localizer=localizer,
        permission_repository=permission_repository,
    )
    ChannelCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        irc_manager=irc_adapter,
        localizer=localizer,
        permission_repository=permission_repository,
    )
    ChannelEventCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        adapter_event_repository=adapter_event_repository,
        adapter_event_action_repository=adapter_event_action_repository,
        twitch_api=twitch_api,
        permission_repository=permission_repository,
        localizer=localizer,
    )
    ChannelLiveStatePersistenceService(
        event_bus=event_bus,
        channel_repository=channel_repository,
    )
    DiscordUIFlowGuardService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        permission_repository=permission_repository,
        localizer=localizer,
    )
    UserCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        tracked_user_repository=tracked_user_repository,
        twitch_api=twitch_api,
        localizer=localizer,
        permission_repository=permission_repository,
    )
    discord_adapter = DiscordAdapter(
        config=config,
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        tracked_user_repository=tracked_user_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        adapter_event_repository=adapter_event_repository,
        adapter_event_action_repository=adapter_event_action_repository,
        twitch_api=twitch_api,
        localizer=localizer,
    )
    device_flow_poller = DeviceFlowPollingService(
        device_flow_repository=device_flow_repository,
        account_repository=account_repository,
        thread_repository=thread_repository,
        twitch_api=twitch_api,
        notifier=discord_adapter,
        poll_interval_seconds=config.twitch_device_flow_poll_interval_seconds,
        localizer=localizer,
    )
    presence_service = DiscordPresenceService(
        message_repository=message_repository,
        notifier=discord_adapter,
        poll_interval_seconds=config.discord_presence_poll_interval_seconds,
        lookback_minutes=config.discord_presence_lookback_minutes,
        message_limit=config.discord_presence_message_limit,
        max_status_length=config.discord_presence_max_status_length,
    )
    irc_bootstrap_service = IRCBootstrapService(
        channel_repository=channel_repository,
        twitch_api=twitch_api,
        irc_manager=irc_adapter,
        connect_timeout_seconds=config.irc_bootstrap_connect_timeout_seconds,
        resync_interval_seconds=config.irc_channel_resync_interval_seconds,
    )
    PatternCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        tracked_user_repository=tracked_user_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        permission_repository=permission_repository,
        localizer=localizer,
    )
    PermissionCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        permission_repository=permission_repository,
        localizer=localizer,
    )
    ReplyCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
        adapter_event_repository=adapter_event_repository,
        adapter_event_action_repository=adapter_event_action_repository,
        permission_repository=permission_repository,
        localizer=localizer,
    )
    ShowCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        tracked_user_repository=tracked_user_repository,
        adapter_event_repository=adapter_event_repository,
        adapter_event_action_repository=adapter_event_action_repository,
        twitch_api=twitch_api,
        localizer=localizer,
        permission_repository=permission_repository,
        account_repository=account_repository,
        device_flow_repository=device_flow_repository,
    )
    PatternTrackingService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        tracked_user_repository=tracked_user_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,
        notifier=discord_adapter,
        localizer=localizer,
        reply_repository=reply_repository,
    )
    AutoReplyService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        tracked_user_repository=tracked_user_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
        notifier=discord_adapter,
        token_refresh_skew_seconds=config.twitch_account_token_refresh_skew_seconds,
    )
    ChannelEventAutoReplyService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        adapter_event_repository=adapter_event_repository,
        adapter_event_action_repository=adapter_event_action_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
        notifier=discord_adapter,
        token_refresh_skew_seconds=config.twitch_account_token_refresh_skew_seconds,
    )
    ChannelEventNotificationService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        adapter_event_repository=adapter_event_repository,
        adapter_event_action_repository=adapter_event_action_repository,
        notifier=discord_adapter,
        localizer=localizer,
    )
    TwitchWriteCommandService(
        event_bus=event_bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,
        permission_repository=permission_repository,
        token_refresh_skew_seconds=config.twitch_account_token_refresh_skew_seconds,
        localizer=localizer,
    )

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, _request_stop)

    irc_task = asyncio.create_task(irc_adapter.start(), name="twitch-irc-adapter")
    irc_task.add_done_callback(_log_background_task_failure)
    live_monitor_service = TwitchLiveMonitorService(
        event_bus=event_bus,
        channel_repository=channel_repository,
        twitch_api=twitch_api,
        poll_interval_seconds=config.twitch_live_monitor_poll_interval_seconds,
        batch_size=config.twitch_live_monitor_batch_size,
        refresh_on_startup=config.twitch_live_monitor_refresh_on_startup,
    )
    await live_monitor_service.start()
    discord_task = asyncio.create_task(discord_adapter.start(), name="discord-adapter")
    discord_task.add_done_callback(_log_background_task_failure)
    await irc_bootstrap_service.sync_persisted_channels()
    await irc_bootstrap_service.start_periodic_sync()
    await device_flow_poller.start()
    await presence_service.start()

    try:
        await stop_event.wait()
    finally:
        irc_task.cancel()
        discord_task.cancel()
        with suppress(asyncio.CancelledError):
            await irc_task
        with suppress(asyncio.CancelledError):
            await discord_task
        await live_monitor_service.stop()
        await irc_bootstrap_service.stop_periodic_sync()
        await device_flow_poller.stop()
        await presence_service.stop()
        await twitch_api.close()
        await discord_adapter.stop()
        await irc_adapter.stop()
        database.close()


def main() -> None:
    """Start the async application runtime."""
    asyncio.run(_run())


def _log_background_task_failure(task: asyncio.Task[object]) -> None:
    """Log unexpected background task failures immediately."""
    if task.cancelled():
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return
    if error is not None:
        logging.getLogger(__name__).error(
            "Background task %s stopped unexpectedly.",
            task.get_name(),
            exc_info=(type(error), error, error.__traceback__),
        )


if __name__ == "__main__":
    main()
