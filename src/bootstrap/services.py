"""Service and query assembly."""

from __future__ import annotations

from dataclasses import dataclass

from src.entrypoints.discord import DiscordServiceBundle
from src.services.account_service import AccountCommandService
from src.services.chat import ChatMessageReactionService, ChatPatternMatcher
from src.services.channel_command_service import ChannelCommandService
from src.services.channel_event_notification_service import (
    ChannelEventNotificationService,
    ChannelLiveStatePersistenceService,
)
from src.services.channel_live_state_service import ChannelEventCommandService
from src.services.chat_pipeline import ChatMessageProcessingService
from src.services.discord_ui_queries import (
    AdapterEventQueryService,
    DiscordUIQueryBundle,
    PatternQueryService,
    ReplyQueryService,
    TrackedChannelQueryService,
    TrackedUserQueryService,
    WriteQueryService,
)
from src.services.live_state_orchestrator import LiveStateChangeOrchestrator
from src.services.message_ingest_service import MessageIngestService
from src.services.patterns import PatternCommandService, PatternTrackingService, ShowCommandService
from src.services.permission_service import PermissionCommandService
from src.services.replies import AutoReplyService, ChannelEventAutoReplyService, ReplyCommandService, ReplyEventConfiguration
from src.services.runtime_coordinator import ApplicationRuntimeCoordinator
from src.services.thread_lifecycle_service import ThreadLifecycleService
from src.services.twitch_user_directory_service import TwitchUserDirectoryIngestService
from src.services.ui_flow_service import DiscordUIFlowGuardService
from src.services.user_command_service import UserCommandService
from src.services.write_service import TwitchWriteCommandService

from .models import ApplicationCore, ApplicationGateways, ApplicationServices


@dataclass(slots=True)
class _ChatProcessingServices:
    pattern_tracking: PatternTrackingService
    auto_reply: AutoReplyService
    chat_reactions: ChatMessageReactionService
    chat_pipeline: ChatMessageProcessingService


@dataclass(slots=True)
class _LiveStateServices:
    live_state_persistence: ChannelLiveStatePersistenceService
    channel_event_notification: ChannelEventNotificationService
    channel_event_auto_reply: ChannelEventAutoReplyService
    live_state_orchestrator: LiveStateChangeOrchestrator


def build_services(core: ApplicationCore, gateways: ApplicationGateways) -> ApplicationServices:
    message_ingest = MessageIngestService(message_repository=core.message_repository)
    user_directory_ingest = TwitchUserDirectoryIngestService(directory=core.twitch_directory)
    ui_queries = _build_ui_queries(core)
    runtime_coordinator = ApplicationRuntimeCoordinator()
    discord_bundle = _build_discord_bundle(core, gateways, runtime_coordinator)
    shared_chat_matcher = ChatPatternMatcher(pattern_repository=core.pattern_repository)
    chat_processing = _build_chat_processing_services(
        core,
        runtime_coordinator=runtime_coordinator,
        matcher=shared_chat_matcher,
        message_ingest=message_ingest,
        user_directory_ingest=user_directory_ingest,
    )
    live_state = _build_live_state_services(core, runtime_coordinator=runtime_coordinator)
    return ApplicationServices(
        discord=discord_bundle,
        message_ingest=message_ingest,
        user_directory_ingest=user_directory_ingest,
        pattern_tracking=chat_processing.pattern_tracking,
        auto_reply=chat_processing.auto_reply,
        chat_reactions=chat_processing.chat_reactions,
        live_state_persistence=live_state.live_state_persistence,
        channel_event_notification=live_state.channel_event_notification,
        channel_event_auto_reply=live_state.channel_event_auto_reply,
        chat_pipeline=chat_processing.chat_pipeline,
        live_state_orchestrator=live_state.live_state_orchestrator,
        ui_queries=ui_queries,
        runtime_coordinator=runtime_coordinator,
    )


def _build_ui_queries(core: ApplicationCore) -> DiscordUIQueryBundle:
    tracked_channel_queries = TrackedChannelQueryService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        twitch_api=core.twitch_bundle,
    )
    pattern_queries = PatternQueryService(
        thread_repository=core.thread_repository,
        pattern_repository=core.pattern_repository,
        twitch_api=core.twitch_bundle,
    )
    tracked_user_queries = TrackedUserQueryService(
        thread_repository=core.thread_repository,
        tracked_user_repository=core.tracked_user_repository,
        twitch_api=core.twitch_bundle,
    )
    reply_queries = ReplyQueryService(
        thread_repository=core.thread_repository,
        reply_repository=core.reply_repository,
        pattern_queries=pattern_queries,
    )
    event_queries = AdapterEventQueryService(
        thread_repository=core.thread_repository,
        channel_queries=tracked_channel_queries,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
    )
    write_queries = WriteQueryService(
        thread_repository=core.thread_repository,
        message_repository=core.message_repository,
    )
    return DiscordUIQueryBundle(
        channels=tracked_channel_queries,
        patterns=pattern_queries,
        users=tracked_user_queries,
        replies=reply_queries,
        events=event_queries,
        write=write_queries,
    )


def _build_discord_bundle(
    core: ApplicationCore,
    gateways: ApplicationGateways,
    runtime_coordinator: ApplicationRuntimeCoordinator,
) -> DiscordServiceBundle:
    thread_service = ThreadLifecycleService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        twitch_api=core.twitch_bundle,
        irc_gateway=gateways.twitch_irc,
        localizer=core.localizer,
        permission_repository=core.permission_repository,
        tracked_channels_notifier=runtime_coordinator.tracked_channels,
    )
    channel_service = ChannelCommandService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        pattern_repository=core.pattern_repository,
        twitch_api=core.twitch_bundle,
        irc_gateway=gateways.twitch_irc,
        localizer=core.localizer,
        permission_repository=core.permission_repository,
        tracked_channels_notifier=runtime_coordinator.tracked_channels,
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
        pattern_repository=core.pattern_repository,
        reply_repository=core.reply_repository,
        account_repository=core.account_repository,
        event_configuration=ReplyEventConfiguration(
            adapter_event_repository=core.adapter_event_repository,
            adapter_event_action_repository=core.adapter_event_action_repository,
            twitch_api=core.twitch_bundle,
        ),
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
    return DiscordServiceBundle(
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


def _build_chat_processing_services(
    core: ApplicationCore,
    *,
    runtime_coordinator: ApplicationRuntimeCoordinator,
    matcher: ChatPatternMatcher,
    message_ingest: MessageIngestService,
    user_directory_ingest: TwitchUserDirectoryIngestService,
) -> _ChatProcessingServices:
    pattern_tracking = PatternTrackingService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        pattern_repository=core.pattern_repository,
        message_repository=core.message_repository,
        twitch_api=core.twitch_bundle,
        notifier=runtime_coordinator.tracking,
        localizer=core.localizer,
        matcher=matcher,
    )
    auto_reply = AutoReplyService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        pattern_repository=core.pattern_repository,
        message_repository=core.message_repository,
        account_repository=core.account_repository,
        twitch_api=core.twitch_bundle,
        tracking_notifier=runtime_coordinator.tracking,
        account_notifier=runtime_coordinator.accounts,
        token_refresh_skew_seconds=core.config.twitch_account_token_refresh_skew_seconds,
        matcher=matcher,
    )
    chat_reactions = ChatMessageReactionService(
        matcher=matcher,
        tracking=pattern_tracking,
        replies=auto_reply,
    )
    chat_pipeline = ChatMessageProcessingService(
        message_ingest=message_ingest,
        user_observer=user_directory_ingest,
        reactions=chat_reactions,
    )
    return _ChatProcessingServices(
        pattern_tracking=pattern_tracking,
        auto_reply=auto_reply,
        chat_reactions=chat_reactions,
        chat_pipeline=chat_pipeline,
    )


def _build_live_state_services(
    core: ApplicationCore,
    *,
    runtime_coordinator: ApplicationRuntimeCoordinator,
) -> _LiveStateServices:
    live_state_persistence = ChannelLiveStatePersistenceService(channel_repository=core.channel_repository)
    channel_event_notification = ChannelEventNotificationService(
        thread_repository=core.thread_repository,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
        channel_repository=core.channel_repository,
        twitch_api=core.twitch_bundle,
        notifier=runtime_coordinator.channel_results,
        localizer=core.localizer,
    )
    channel_event_auto_reply = ChannelEventAutoReplyService(
        thread_repository=core.thread_repository,
        channel_repository=core.channel_repository,
        adapter_event_repository=core.adapter_event_repository,
        adapter_event_action_repository=core.adapter_event_action_repository,
        account_repository=core.account_repository,
        twitch_api=core.twitch_bundle,
        tracking_notifier=runtime_coordinator.tracking,
        token_refresh_skew_seconds=core.config.twitch_account_token_refresh_skew_seconds,
        localizer=core.localizer,
    )
    live_state_orchestrator = LiveStateChangeOrchestrator(
        persistence=live_state_persistence,
        notifications=channel_event_notification,
        auto_replies=channel_event_auto_reply,
    )
    return _LiveStateServices(
        live_state_persistence=live_state_persistence,
        channel_event_notification=channel_event_notification,
        channel_event_auto_reply=channel_event_auto_reply,
        live_state_orchestrator=live_state_orchestrator,
    )
