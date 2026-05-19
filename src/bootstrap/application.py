"""Runtime assembly for the direct-call application architecture."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass

from src.config import AppConfig
from src.database.postgres import (
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
from src.entrypoints.discord import DiscordEntrypoint, DiscordServiceBundle
from src.entrypoints.twitch_irc import TwitchIRCEntrypoint
from src.gateways.twitch_api import TwitchAPIClient
from src.gateways.twitch_irc import AnonymousTwitchIRCGateway
from src.localization import Localizer
from src.services.account_polling_service import DeviceFlowPollingService
from src.services.account_service import AccountCommandService
from src.services.channel_command_service import ChannelCommandService
from src.services.channel_event_notification_service import (
    ChannelEventNotificationService,
    ChannelLiveStatePersistenceService,
)
from src.services.channel_live_state_service import ChannelEventCommandService
from src.services.chat_pipeline import ChatMessageProcessingService
from src.services.discord_presence_service import DiscordPresenceService
from src.services.irc_bootstrap_service import IRCBootstrapService
from src.services.live_state_orchestrator import LiveStateChangeOrchestrator
from src.services.message_ingest_service import MessageIngestService
from src.services.patterns import PatternCommandService, PatternTrackingService, ShowCommandService
from src.services.permission_service import PermissionCommandService
from src.services.replies import AutoReplyService, ChannelEventAutoReplyService, ReplyCommandService
from src.services.thread_lifecycle_service import ThreadLifecycleService
from src.services.twitch_auth_service import TwitchAuthService
from src.services.twitch_chat_write_service import TwitchChatWriteService
from src.services.twitch_live_monitor_service import TwitchLiveMonitorService
from src.services.twitch_live_query_service import TwitchLiveQueryService
from src.services.twitch_service_bundle import TwitchServiceBundle
from src.services.twitch_user_directory_service import TwitchUserDirectoryIngestService, TwitchUserDirectoryService
from src.services.ui_flow_service import DiscordUIFlowGuardService
from src.services.user_command_service import UserCommandService
from src.services.write_service import TwitchWriteCommandService


@dataclass(slots=True)
class ApplicationCore:
    """Core repositories and shared integration services used across the runtime."""

    config: AppConfig
    localizer: Localizer
    database: PostgresDatabase
    message_repository: PostgresMessageRepository
    thread_repository: PostgresThreadRepository
    channel_repository: PostgresChannelRepository
    tracked_user_repository: PostgresTrackedUserRepository
    pattern_repository: PostgresPatternRepository
    reply_repository: PostgresReplyRepository
    adapter_event_repository: PostgresAdapterEventRepository
    adapter_event_action_repository: PostgresAdapterEventActionRepository
    permission_repository: PostgresUserPermissionRepository
    account_repository: PostgresTwitchAccountRepository
    device_flow_repository: PostgresTwitchDeviceFlowRepository
    twitch_user_cache_repository: PostgresTwitchUserCacheRepository
    raw_twitch_api: TwitchAPIClient
    twitch_directory: TwitchUserDirectoryService
    twitch_bundle: TwitchServiceBundle


@dataclass(slots=True)
class ApplicationServices:
    """Direct business services, pipelines, and orchestrators."""

    discord: DiscordServiceBundle
    message_ingest: MessageIngestService
    user_directory_ingest: TwitchUserDirectoryIngestService
    pattern_tracking: PatternTrackingService
    auto_reply: AutoReplyService
    live_state_persistence: ChannelLiveStatePersistenceService
    channel_event_notification: ChannelEventNotificationService
    channel_event_auto_reply: ChannelEventAutoReplyService
    chat_pipeline: ChatMessageProcessingService
    live_state_orchestrator: LiveStateChangeOrchestrator


@dataclass(slots=True)
class ApplicationGateways:
    """Concrete external gateways bound into the runtime."""

    twitch_irc: AnonymousTwitchIRCGateway


@dataclass(slots=True)
class ApplicationEntrypoints:
    """Concrete external entrypoints bound into the runtime."""

    twitch_irc: TwitchIRCEntrypoint
    discord: DiscordEntrypoint


@dataclass(slots=True)
class ApplicationRuntime:
    """Long-lived runtime components that need explicit start/stop handling."""

    live_monitor_service: TwitchLiveMonitorService
    irc_bootstrap_service: IRCBootstrapService
    device_flow_poller: DeviceFlowPollingService
    presence_service: DiscordPresenceService
    twitch_irc_task: asyncio.Task[None]
    discord_task: asyncio.Task[None]


def build_core(config: AppConfig) -> ApplicationCore:
    """Create shared repositories and external Twitch-facing services."""
    localizer = Localizer.from_directory()
    database = PostgresDatabase(config)
    core = ApplicationCore(
        config=config,
        localizer=localizer,
        database=database,
        message_repository=PostgresMessageRepository(database),
        thread_repository=PostgresThreadRepository(database),
        channel_repository=PostgresChannelRepository(database),
        tracked_user_repository=PostgresTrackedUserRepository(database),
        pattern_repository=PostgresPatternRepository(database),
        reply_repository=PostgresReplyRepository(database),
        adapter_event_repository=PostgresAdapterEventRepository(database),
        adapter_event_action_repository=PostgresAdapterEventActionRepository(database),
        permission_repository=PostgresUserPermissionRepository(database),
        account_repository=PostgresTwitchAccountRepository(database),
        device_flow_repository=PostgresTwitchDeviceFlowRepository(database),
        twitch_user_cache_repository=PostgresTwitchUserCacheRepository(database),
        raw_twitch_api=TwitchAPIClient(config),
        twitch_directory=None,  # type: ignore[arg-type]
        twitch_bundle=None,  # type: ignore[arg-type]
    )
    core.twitch_directory = TwitchUserDirectoryService(
        twitch_api=core.raw_twitch_api,
        repository=core.twitch_user_cache_repository,
        memory_cache_size=config.twitch_user_cache_memory_size,
        api_refresh_interval_seconds=config.twitch_user_cache_api_refresh_seconds,
        channel_api_refresh_interval_seconds=config.twitch_channel_cache_api_refresh_seconds,
    )
    core.twitch_bundle = TwitchServiceBundle(
        directory=core.twitch_directory,
        auth=TwitchAuthService(core.raw_twitch_api),
        chat=TwitchChatWriteService(core.raw_twitch_api),
        live=TwitchLiveQueryService(core.raw_twitch_api),
    )
    database.healthcheck()
    return core


def build_gateways(core: ApplicationCore) -> ApplicationGateways:
    """Create concrete external gateways used by services and entrypoints."""
    return ApplicationGateways(twitch_irc=AnonymousTwitchIRCGateway(core.config))


def build_services(core: ApplicationCore, gateways: ApplicationGateways) -> ApplicationServices:
    """Create direct command services, pipelines, and orchestrators."""
    message_ingest = MessageIngestService(message_repository=core.message_repository)
    user_directory_ingest = TwitchUserDirectoryIngestService(directory=core.twitch_directory)

    thread_service = ThreadLifecycleService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        twitch_api=core.twitch_bundle,
        irc_gateway=gateways.twitch_irc,
        localizer=core.localizer,
        permission_repository=core.permission_repository,
    )
    channel_service = ChannelCommandService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        pattern_repository=core.pattern_repository,
        twitch_api=core.twitch_bundle,
        irc_gateway=gateways.twitch_irc,
        localizer=core.localizer,
        permission_repository=core.permission_repository,
    )
    user_service = UserCommandService(
        thread_repository=core.thread_repository,
        tracked_user_repository=core.tracked_user_repository,
        twitch_user_lookup=core.twitch_bundle,
        localizer=core.localizer,
        permission_repository=core.permission_repository,
    )
    pattern_service = PatternCommandService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        tracked_user_repository=core.tracked_user_repository,
        pattern_repository=core.pattern_repository,
        twitch_api=core.twitch_bundle,
        permission_repository=core.permission_repository,
        localizer=core.localizer,
    )
    permission_service = PermissionCommandService(
        thread_repository=core.thread_repository,
        permission_repository=core.permission_repository,
        localizer=core.localizer,
    )
    account_service = AccountCommandService(
        account_repository=core.account_repository,
        device_flow_repository=core.device_flow_repository,
        thread_repository=core.thread_repository,
        twitch_api=core.twitch_bundle,
        permission_repository=core.permission_repository,
        localizer=core.localizer,
    )
    reply_service = ReplyCommandService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        pattern_repository=core.pattern_repository,
        reply_repository=core.reply_repository,
        account_repository=core.account_repository,
        twitch_api=core.twitch_bundle,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
        permission_repository=core.permission_repository,
        localizer=core.localizer,
    )
    write_service = TwitchWriteCommandService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        account_repository=core.account_repository,
        twitch_api=core.twitch_bundle,
        permission_repository=core.permission_repository,
        token_refresh_skew_seconds=core.config.twitch_account_token_refresh_skew_seconds,
        localizer=core.localizer,
    )
    show_service = ShowCommandService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        pattern_repository=core.pattern_repository,
        reply_repository=core.reply_repository,
        tracked_user_repository=core.tracked_user_repository,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
        twitch_api=core.twitch_bundle,
        localizer=core.localizer,
        permission_repository=core.permission_repository,
        account_repository=core.account_repository,
        device_flow_repository=core.device_flow_repository,
    )
    channel_event_service = ChannelEventCommandService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
        twitch_api=core.twitch_bundle,
        permission_repository=core.permission_repository,
        localizer=core.localizer,
    )
    ui_flow_guard = DiscordUIFlowGuardService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        pattern_repository=core.pattern_repository,
        reply_repository=core.reply_repository,
        account_repository=core.account_repository,
        permission_repository=core.permission_repository,
        localizer=core.localizer,
    )
    pattern_tracking = PatternTrackingService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        tracked_user_repository=core.tracked_user_repository,
        pattern_repository=core.pattern_repository,
        reply_repository=core.reply_repository,
        twitch_api=core.twitch_bundle,
        notifier=None,
        localizer=core.localizer,
    )
    auto_reply = AutoReplyService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        tracked_user_repository=core.tracked_user_repository,
        pattern_repository=core.pattern_repository,
        reply_repository=core.reply_repository,
        account_repository=core.account_repository,
        twitch_api=core.twitch_bundle,
        notifier=None,
        token_refresh_skew_seconds=core.config.twitch_account_token_refresh_skew_seconds,
    )
    live_state_persistence = ChannelLiveStatePersistenceService(channel_repository=core.channel_repository)
    channel_event_notification = ChannelEventNotificationService(
        thread_repository=core.thread_repository,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
        notifier=None,
        localizer=core.localizer,
    )
    channel_event_auto_reply = ChannelEventAutoReplyService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
        account_repository=core.account_repository,
        twitch_api=core.twitch_bundle,
        notifier=None,
        token_refresh_skew_seconds=core.config.twitch_account_token_refresh_skew_seconds,
    )
    chat_pipeline = ChatMessageProcessingService(
        message_ingest=message_ingest,
        user_observer=user_directory_ingest,
        pattern_tracking=pattern_tracking,
        auto_reply=auto_reply,
    )
    live_state_orchestrator = LiveStateChangeOrchestrator(
        persistence=live_state_persistence,
        notifications=channel_event_notification,
        auto_replies=channel_event_auto_reply,
    )
    discord_bundle = DiscordServiceBundle(
        thread=thread_service,
        channel=channel_service,
        user=user_service,
        pattern=pattern_service,
        permission=permission_service,
        account=account_service,
        reply=reply_service,
        write=write_service,
        show=show_service,
        channel_event=channel_event_service,
        ui_flow_guard=ui_flow_guard,
    )
    return ApplicationServices(
        discord=discord_bundle,
        message_ingest=message_ingest,
        user_directory_ingest=user_directory_ingest,
        pattern_tracking=pattern_tracking,
        auto_reply=auto_reply,
        live_state_persistence=live_state_persistence,
        channel_event_notification=channel_event_notification,
        channel_event_auto_reply=channel_event_auto_reply,
        chat_pipeline=chat_pipeline,
        live_state_orchestrator=live_state_orchestrator,
    )


def build_entrypoints(
    core: ApplicationCore,
    services: ApplicationServices,
    gateways: ApplicationGateways,
) -> ApplicationEntrypoints:
    """Create runtime entrypoints and bind direct collaborators."""
    discord_entrypoint = DiscordEntrypoint(
        config=core.config,
        services=services.discord,
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        tracked_user_repository=core.tracked_user_repository,
        pattern_repository=core.pattern_repository,
        reply_repository=core.reply_repository,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
        twitch_api=core.twitch_bundle,
        localizer=core.localizer,
    )
    services.pattern_tracking.notifier = discord_entrypoint
    services.auto_reply.notifier = discord_entrypoint
    services.channel_event_notification.notifier = discord_entrypoint
    services.channel_event_auto_reply.notifier = discord_entrypoint
    twitch_irc_entrypoint = TwitchIRCEntrypoint(gateways.twitch_irc, message_processor=services.chat_pipeline)
    return ApplicationEntrypoints(twitch_irc=twitch_irc_entrypoint, discord=discord_entrypoint)


def build_runtime(
    core: ApplicationCore, services: ApplicationServices, gateways: ApplicationGateways, entrypoints: ApplicationEntrypoints
) -> ApplicationRuntime:
    """Create long-lived runtime workers and wire direct callbacks."""
    live_monitor_service = TwitchLiveMonitorService(
        channel_repository=core.channel_repository,
        twitch_api=core.twitch_bundle,
        poll_interval_seconds=core.config.twitch_live_monitor_poll_interval_seconds,
        batch_size=core.config.twitch_live_monitor_batch_size,
        refresh_on_startup=core.config.twitch_live_monitor_refresh_on_startup,
        on_change=services.live_state_orchestrator.handle_change,
    )
    services.discord.thread.tracked_channels_changed = live_monitor_service.notify_tracked_channels_changed
    services.discord.channel.tracked_channels_changed = live_monitor_service.notify_tracked_channels_changed

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


async def start_runtime(runtime: ApplicationRuntime) -> None:
    """Start background runtime workers in the required order."""
    await runtime.live_monitor_service.start()
    await runtime.irc_bootstrap_service.sync_persisted_channels()
    await runtime.irc_bootstrap_service.start_periodic_sync()
    await runtime.device_flow_poller.start()
    await runtime.presence_service.start()


async def stop_runtime(core: ApplicationCore, entrypoints: ApplicationEntrypoints, runtime: ApplicationRuntime) -> None:
    """Stop the runtime and release external resources in reverse order."""
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
