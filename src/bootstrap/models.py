"""Bootstrap dataclasses shared across assembly stages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.config import AppConfig
from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRepository,
    MessageRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRepository,
    TrackedUserRepository,
    TwitchAccountRepository,
    TwitchDeviceFlowRepository,
    TwitchUserCacheRepository,
    UserPermissionRepository,
)
from src.database.postgres import PostgresDatabase
from src.gateways.twitch_api import TwitchAPIClient
from src.gateways.twitch_irc import AnonymousTwitchIRCGateway
from src.localization import Localizer
from src.services.channel_event_notification_service import (
    ChannelEventNotificationService,
    ChannelLiveStatePersistenceService,
)
from src.services.chat_pipeline import ChatMessageProcessingService
from src.services.discord_ui_query_service import DiscordUIQueryBundle
from src.services.live_state_orchestrator import LiveStateChangeOrchestrator
from src.services.message_ingest_service import MessageIngestService
from src.services.patterns import PatternTrackingService
from src.services.replies import AutoReplyService, ChannelEventAutoReplyService
from src.services.runtime_coordinator import ApplicationRuntimeCoordinator
from src.services.twitch_service_bundle import TwitchServiceBundle
from src.services.twitch_user_directory_service import TwitchUserDirectoryIngestService, TwitchUserDirectoryService

if TYPE_CHECKING:
    from src.entrypoints.discord import DiscordEntrypoint, DiscordServiceBundle
    from src.entrypoints.twitch_irc import TwitchIRCEntrypoint
    from src.services.account_polling_service import DeviceFlowPollingService
    from src.services.discord_presence_service import DiscordPresenceService
    from src.services.irc_bootstrap_service import IRCBootstrapService
    from src.services.twitch_live_monitor_service import TwitchLiveMonitorService


@dataclass(slots=True)
class ApplicationCore:
    config: AppConfig
    localizer: Localizer
    database: PostgresDatabase
    message_repository: MessageRepository
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    tracked_user_repository: TrackedUserRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    permission_repository: UserPermissionRepository
    account_repository: TwitchAccountRepository
    device_flow_repository: TwitchDeviceFlowRepository
    twitch_user_cache_repository: TwitchUserCacheRepository
    raw_twitch_api: TwitchAPIClient
    twitch_directory: TwitchUserDirectoryService
    twitch_bundle: TwitchServiceBundle


@dataclass(slots=True)
class ApplicationServices:
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
    ui_queries: DiscordUIQueryBundle
    runtime_coordinator: ApplicationRuntimeCoordinator


@dataclass(slots=True)
class ApplicationGateways:
    twitch_irc: AnonymousTwitchIRCGateway


@dataclass(slots=True)
class ApplicationEntrypoints:
    twitch_irc: TwitchIRCEntrypoint
    discord: DiscordEntrypoint


@dataclass(slots=True)
class ApplicationRuntime:
    live_monitor_service: TwitchLiveMonitorService
    irc_bootstrap_service: IRCBootstrapService
    device_flow_poller: DeviceFlowPollingService
    presence_service: DiscordPresenceService
    twitch_irc_task: asyncio.Task[None] | None = None
    discord_task: asyncio.Task[None] | None = None
