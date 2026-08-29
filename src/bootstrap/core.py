"""Core and gateway assembly."""

from __future__ import annotations

from src.config import AppConfig
from src.database.postgres import (
    PostgresAdapterEventActionRepository,
    PostgresAdapterEventRepository,
    PostgresChannelRepository,
    PostgresDatabase,
    PostgresMigrationRunner,
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
from src.gateways.twitch_api import TwitchAPIClient
from src.gateways.twitch_irc import AnonymousTwitchIRCGateway
from src.localization import Localizer
from src.services.twitch_auth_service import TwitchAuthService
from src.services.batched_message_repository import BatchedMessageRepository
from src.services.twitch_chat_write_service import TwitchChatWriteService
from src.services.twitch_live_query_service import TwitchLiveQueryService
from src.services.twitch_service_bundle import TwitchServiceBundle
from src.services.twitch_user_directory_service import TwitchUserDirectoryService

from .models import ApplicationCore, ApplicationGateways


async def build_core(config: AppConfig) -> ApplicationCore:
    localizer = Localizer.from_directory()
    database = PostgresDatabase(config)
    await database.open()
    await PostgresMigrationRunner(database=database).apply_pending()
    raw_message_repository = PostgresMessageRepository(database)
    message_repository = BatchedMessageRepository(
        repository=raw_message_repository,
        batch_size=max(1, config.twitch_message_write_batch_size),
        flush_interval_seconds=max(0.0, config.twitch_message_write_flush_interval_seconds),
        spool_path=config.twitch_message_write_spool_path,
    )
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
    raw_twitch_api = TwitchAPIClient(config)
    twitch_directory = TwitchUserDirectoryService(
        twitch_api=raw_twitch_api,
        repository=twitch_user_cache_repository,
        memory_cache_size=config.twitch_user_cache_memory_size,
    )
    twitch_bundle = TwitchServiceBundle(
        directory=twitch_directory,
        auth=TwitchAuthService(raw_twitch_api),
        chat=TwitchChatWriteService(raw_twitch_api),
        live=TwitchLiveQueryService(raw_twitch_api),
    )
    core = ApplicationCore(
        config=config,
        localizer=localizer,
        database=database,
        message_repository=message_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        tracked_user_repository=tracked_user_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        adapter_event_repository=adapter_event_repository,
        adapter_event_action_repository=adapter_event_action_repository,
        permission_repository=permission_repository,
        account_repository=account_repository,
        device_flow_repository=device_flow_repository,
        twitch_user_cache_repository=twitch_user_cache_repository,
        raw_twitch_api=raw_twitch_api,
        twitch_directory=twitch_directory,
        twitch_bundle=twitch_bundle,
    )
    await database.healthcheck()
    return core


def build_gateways(core: ApplicationCore) -> ApplicationGateways:
    return ApplicationGateways(twitch_irc=AnonymousTwitchIRCGateway(core.config))
