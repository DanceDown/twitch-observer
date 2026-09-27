"""Runtime execution of live/offline event auto-replies."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    AdapterEventRepository,
    ChannelRecord,
    ChannelRepository,
    MessageRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
)
from src.events.twitch_events import TwitchChannelLiveStateChangedEvent, TwitchChatMessageEvent, TwitchChatSendRequest
from src.gateways.twitch_api import TwitchAPIError, TwitchAuthenticationError
from src.localization import Localizer
from src.services.patterns import TrackingNotificationSender
from src.services.twitch_gateways import TwitchReplyGateway
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    DISCORD_NOTIFY_ACTION,
    STREAM_EVENT_KEY_TO_STATE,
    STREAM_OFFLINE_EVENT_KEY,
    STREAM_ONLINE_EVENT_KEY,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
    LinkedTwitchAccountRefreshContext,
    ensure_fresh_linked_account,
    refresh_linked_account,
    safe_get_twitch_user_by_id,
)
from src.utils.discord_embeds import ChannelEventAutoReplyEmbedRequest, build_channel_event_auto_reply_embed

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _EventAutoReplyContext:
    reply: AdapterEventActionRecord
    thread: ThreadRecord
    account: TwitchAccountRecord
    source_channel: ChannelRecord | None
    notify_action: AdapterEventActionRecord | None


@dataclass(slots=True, frozen=True)
class _ChannelEventMetadata:
    event: TwitchChannelLiveStateChangedEvent
    state: str
    channel_name: str
    channel_login: str | None
    channel_icon_url: str | None
    twitch_chat_color: str | None


@dataclass(slots=True)
class ChannelEventAutoReplyService:
    """Send Twitch messages when a tracked channel goes live or offline."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    message_repository: MessageRepository
    account_repository: TwitchAccountRepository
    twitch_api: TwitchReplyGateway
    tracking_notifier: TrackingNotificationSender
    token_refresh_skew_seconds: int
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    async def handle_channel_live_state_changed(
        self,
        event: TwitchChannelLiveStateChangedEvent,
    ) -> set[tuple[int, int]]:
        """Send configured Twitch auto-replies for one live/offline transition."""
        event_key = STREAM_ONLINE_EVENT_KEY if event.is_live else STREAM_OFFLINE_EVENT_KEY
        configured_events = await self.adapter_event_repository.list_matching_events(
            adapter_key=TWITCH_ADAPTER_KEY,
            subject_type=CHANNEL_SUBJECT_TYPE,
            subject_id=event.twitch_channel_id,
            event_key=event_key,
            include_disabled=False,
        )

        if not configured_events:
            return set()

        channel_user = await safe_get_twitch_user_by_id(
            self.twitch_api,
            event.twitch_channel_id,
            require_chat_color=True,
        )
        channel_login = event.twitch_channel_login or (None if channel_user is None else channel_user.login)
        metadata = _ChannelEventMetadata(
            event=event,
            state=STREAM_EVENT_KEY_TO_STATE[event_key],
            channel_name=(event.twitch_channel_login if channel_user is None else channel_user.display_name) or event.twitch_channel_id,
            channel_login=channel_login,
            channel_icon_url=None if channel_user is None else channel_user.profile_image_url,
            twitch_chat_color=None if channel_user is None else channel_user.chat_color,
        )
        task_results = await asyncio.gather(
            *[
                self._handle_configured_event_auto_reply(
                    configured_event=configured_event,
                    metadata=metadata,
                )
                for configured_event in configured_events
            ],
            return_exceptions=True,
        )
        sent_event_keys: set[tuple[int, int]] = set()
        for configured_event, result in zip(configured_events, task_results, strict=False):
            if isinstance(result, Exception):
                logger.exception(
                    "Channel-event auto-reply worker failed thread_id=%s event_id=%s twitch_channel_id=%s state=%s",
                    configured_event.thread_id,
                    configured_event.event_id,
                    event.twitch_channel_id,
                    metadata.state,
                    exc_info=(type(result), result, result.__traceback__),
                )
                continue
            if result is not None:
                sent_event_keys.add(result)
        return sent_event_keys

    async def _handle_configured_event_auto_reply(
        self,
        *,
        configured_event: AdapterEventRecord,
        metadata: _ChannelEventMetadata,
    ) -> tuple[int, int] | None:
        context = await self._load_event_auto_reply_context(
            configured_event=configured_event,
            twitch_channel_id=metadata.event.twitch_channel_id,
        )
        if context is None:
            return None
        refresh_context = LinkedTwitchAccountRefreshContext(
            account_repository=self.account_repository,
            twitch_auth=self.twitch_api,
            thread_repository=self.thread_repository,
            thread=context.thread,
        )
        account = (
            await ensure_fresh_linked_account(
                account=context.account,
                context=refresh_context,
                token_refresh_skew_seconds=self.token_refresh_skew_seconds,
            )
            or context.account
        )
        rendered_message = self._render_channel_event_reply(
            context.reply.message_template or "",
            channel_name=metadata.channel_name,
            state=metadata.state,
        )
        try:
            return await self._send_channel_event_auto_reply(
                configured_event=configured_event,
                context=context,
                account=account,
                metadata=metadata,
                rendered_message=rendered_message,
            )
        except TwitchAuthenticationError:
            refreshed = await refresh_linked_account(
                account=account,
                context=refresh_context,
            )
            if refreshed is None:
                return None
            return await self._send_channel_event_auto_reply(
                configured_event=configured_event,
                context=context,
                account=refreshed,
                metadata=metadata,
                rendered_message=rendered_message,
            )
        except TwitchAPIError as error:
            logger.warning(
                "Failed to send channel-event auto-reply thread_id=%s twitch_channel_id=%s state=%s channel_login=%s: %s",
                configured_event.thread_id,
                metadata.event.twitch_channel_id,
                metadata.state,
                metadata.channel_login,
                error,
            )
            return None

    async def _load_event_auto_reply_context(
        self,
        *,
        configured_event: AdapterEventRecord,
        twitch_channel_id: str,
    ) -> _EventAutoReplyContext | None:
        reply = await self.adapter_event_action_repository.get_action(
            event_id=configured_event.event_id,
            action_type=TWITCH_SEND_MESSAGE_ACTION,
        )
        if reply is None or reply.disabled or not reply.message_template:
            return None

        thread = await self.thread_repository.get_by_thread_id(configured_event.thread_id)
        if thread is None or not thread.enabled:
            return None

        account = await self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
        if account is None or not account.access_token:
            return None

        source_channel = await self.channel_repository.get_by_thread_and_twitch_channel(
            thread.thread_id,
            twitch_channel_id,
        )
        notify_action = await self.adapter_event_action_repository.get_action(
            event_id=configured_event.event_id,
            action_type=DISCORD_NOTIFY_ACTION,
        )
        return _EventAutoReplyContext(
            reply=reply,
            thread=thread,
            account=account,
            source_channel=source_channel,
            notify_action=notify_action,
        )

    async def _send_channel_event_auto_reply(
        self,
        *,
        configured_event: AdapterEventRecord,
        context: _EventAutoReplyContext,
        account: TwitchAccountRecord,
        metadata: _ChannelEventMetadata,
        rendered_message: str,
    ) -> tuple[int, int]:
        sent_message_id = await self.twitch_api.send_chat_message(
            TwitchChatSendRequest(
                access_token=account.access_token,
                client_id=account.client_id,
                sender_id=account.twitch_user_id,
                broadcaster_id=metadata.event.twitch_channel_id,
                message=rendered_message,
            )
        )
        sender_display_name = await self._resolve_account_display_name(account)
        await self.message_repository.save_bot_twitch_message(
            self._build_sent_message_event(
                metadata=metadata,
                account=account,
                message_id=sent_message_id,
                content=rendered_message,
                sender_display_name=sender_display_name,
            )
        )
        await self._notify_auto_reply(
            thread=context.thread,
            source_channel=context.source_channel,
            metadata=metadata,
            reply_message=rendered_message,
            event_color=None if context.notify_action is None else context.notify_action.color,
        )
        return (context.thread.thread_id, configured_event.event_id)

    @staticmethod
    def _render_channel_event_reply(
        template: str,
        *,
        channel_name: str,
        state: str,
    ) -> str:
        rendered = template.replace("{CHANNEL}", channel_name)
        return rendered.replace("{STATE}", state)

    async def _notify_auto_reply(
        self,
        *,
        thread: ThreadRecord,
        source_channel: ChannelRecord | None,
        metadata: _ChannelEventMetadata,
        reply_message: str,
        event_color: str | None,
    ) -> None:
        await self.tracking_notifier.send_tracking_embed(
            thread.discord_channel_id,
            build_channel_event_auto_reply_embed(
                ChannelEventAutoReplyEmbedRequest(
                    thread=thread,
                    localizer=self.localizer,
                    channel_display_name=metadata.channel_name,
                    channel_login=metadata.channel_login or metadata.channel_name,
                    state=metadata.state,
                    reply_message=reply_message,
                    channel=source_channel,
                    event_color=event_color,
                    twitch_chat_color=metadata.twitch_chat_color,
                    channel_icon_url=metadata.channel_icon_url,
                )
            ),
            channel_login=metadata.channel_login,
        )

    @staticmethod
    def _build_sent_message_event(
        *,
        metadata: _ChannelEventMetadata,
        account: TwitchAccountRecord,
        message_id: str,
        content: str,
        sender_display_name: str,
    ) -> TwitchChatMessageEvent:
        return TwitchChatMessageEvent(
            channel_login=metadata.channel_login or metadata.event.twitch_channel_id,
            author_login=account.twitch_login,
            author_display_name=sender_display_name,
            author_id=account.twitch_user_id,
            broadcaster_id=metadata.event.twitch_channel_id,
            message_id=message_id,
            content=content,
            sent_at=datetime.now(UTC),
        )

    async def _resolve_account_display_name(self, account: TwitchAccountRecord) -> str:
        cached = self.twitch_api.get_cached_user_by_id(account.twitch_user_id)
        if cached is None:
            try:
                cached = await self.twitch_api.load_cached_user_by_id(account.twitch_user_id)
            except Exception:
                logger.debug(
                    "Could not load cached Twitch account display name for account_id=%s.",
                    account.account_id,
                    exc_info=True,
                )
        return account.twitch_login if cached is None else cached.display_name
