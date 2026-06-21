"""Runtime execution of live/offline event auto-replies."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.gateways.twitch_api import TwitchAPIError, TwitchAuthenticationError
from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRecord,
    ChannelRepository,
    MessageRepository,
    ThreadRepository,
    TwitchAccountRepository,
)
from src.localization import Localizer
from src.events.twitch_events import TwitchChannelLiveStateChangedEvent, TwitchChatMessageEvent
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
    ensure_fresh_linked_account,
    refresh_linked_account,
    safe_get_twitch_user_by_id,
)
from src.utils.discord_embeds import build_channel_event_auto_reply_embed

logger = logging.getLogger(__name__)


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
        )
        channel_login = event.twitch_channel_login or (None if channel_user is None else channel_user.login)
        channel_name = (event.twitch_channel_login if channel_user is None else channel_user.display_name) or event.twitch_channel_id
        event_state = STREAM_EVENT_KEY_TO_STATE[event_key]
        sent_event_keys: set[tuple[int, int]] = set()
        for configured_event in configured_events:
            reply = await self.adapter_event_action_repository.get_action(
                    event_id=configured_event.event_id,
                    action_type=TWITCH_SEND_MESSAGE_ACTION,
                )
            
            if reply is None or reply.disabled or not reply.message_template:
                continue
            thread = await self.thread_repository.get_by_thread_id(configured_event.thread_id)
            if thread is None or not thread.enabled:
                continue
            account = (
                await self.account_repository.get_by_account_id(thread.account_id)
                if thread.account_id is not None
                else None
            )
            if account is None or not account.access_token:
                continue
            source_channel = await self.channel_repository.get_by_thread_and_twitch_channel(
                    thread.thread_id,
                    event.twitch_channel_id,
                )
            
            notify_action = await self.adapter_event_action_repository.get_action(
                    event_id=configured_event.event_id,
                    action_type=DISCORD_NOTIFY_ACTION,
                )
            
            account = (
                await ensure_fresh_linked_account(
                    account=account,
                    account_repository=self.account_repository,
                    twitch_auth=self.twitch_api,
                    token_refresh_skew_seconds=self.token_refresh_skew_seconds,
                    thread_repository=self.thread_repository,
                    thread=thread,
                )
                or account
            )
            rendered_message = self._render_channel_event_reply(
                reply.message_template,
                channel_name=channel_name,
                state=event_state,
            )
            try:
                sent_message_id = await self.twitch_api.send_chat_message(
                    access_token=account.access_token,
                    client_id=account.client_id,
                    sender_id=account.twitch_user_id,
                    broadcaster_id=event.twitch_channel_id,
                    message=rendered_message,
                )
                await self.message_repository.save_bot_twitch_message(
                    self._build_sent_message_event(
                        channel_login=channel_login or event.twitch_channel_id,
                        author_login=account.twitch_login,
                        author_id=account.twitch_user_id,
                        broadcaster_id=event.twitch_channel_id,
                        message_id=sent_message_id,
                        content=rendered_message,
                    )
                )
                await self._notify_auto_reply(
                    thread=thread,
                    source_channel=source_channel,
                    channel_display_name=channel_name,
                    channel_login=channel_login,
                    channel_icon_url=None if channel_user is None else channel_user.profile_image_url,
                    state=event_state,
                    reply_message=rendered_message,
                    event_color=None if notify_action is None else notify_action.color,
                )
                sent_event_keys.add((thread.thread_id, configured_event.event_id))
            except TwitchAuthenticationError:
                refreshed = await refresh_linked_account(
                    account=account,
                    account_repository=self.account_repository,
                    twitch_auth=self.twitch_api,
                    thread_repository=self.thread_repository,
                    thread=thread,
                )
                if refreshed is None:
                    continue
                sent_message_id = await self.twitch_api.send_chat_message(
                    access_token=refreshed.access_token,
                    client_id=refreshed.client_id,
                    sender_id=refreshed.twitch_user_id,
                    broadcaster_id=event.twitch_channel_id,
                    message=rendered_message,
                )
                await self.message_repository.save_bot_twitch_message(
                    self._build_sent_message_event(
                        channel_login=channel_login or event.twitch_channel_id,
                        author_login=refreshed.twitch_login,
                        author_id=refreshed.twitch_user_id,
                        broadcaster_id=event.twitch_channel_id,
                        message_id=sent_message_id,
                        content=rendered_message,
                    )
                )
                await self._notify_auto_reply(
                    thread=thread,
                    source_channel=source_channel,
                    channel_display_name=channel_name,
                    channel_login=channel_login,
                    channel_icon_url=None if channel_user is None else channel_user.profile_image_url,
                    state=event_state,
                    reply_message=rendered_message,
                    event_color=None if notify_action is None else notify_action.color,
                )
                sent_event_keys.add((thread.thread_id, configured_event.event_id))
            except TwitchAPIError as error:
                logger.warning(
                    "Failed to send channel-event auto-reply thread_id=%s twitch_channel_id=%s state=%s channel_login=%s: %s",
                    configured_event.thread_id,
                    event.twitch_channel_id,
                    event_state,
                    channel_login,
                    error,
                )
        return sent_event_keys

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
        thread,
        source_channel: ChannelRecord | None,
        channel_display_name: str,
        channel_login: str | None,
        channel_icon_url: str | None,
        state: str,
        reply_message: str,
        event_color: str | None,
    ) -> None:
        await self.tracking_notifier.send_tracking_embed(
            thread.discord_channel_id,
            build_channel_event_auto_reply_embed(
                thread=thread,
                localizer=self.localizer,
                channel_display_name=channel_display_name,
                channel_login=channel_login or channel_display_name,
                state=state,
                reply_message=reply_message,
                channel=source_channel,
                event_color=event_color,
                channel_icon_url=channel_icon_url,
            ),
            channel_login=channel_login,
        )

    @staticmethod
    def _build_sent_message_event(
        *,
        channel_login: str,
        author_login: str,
        author_id: str,
        broadcaster_id: str,
        message_id: str,
        content: str,
    ) -> TwitchChatMessageEvent:
        return TwitchChatMessageEvent(
            channel_login=channel_login,
            author_login=author_login,
            author_display_name=author_login,
            author_id=author_id,
            broadcaster_id=broadcaster_id,
            message_id=message_id,
            content=content,
            sent_at=datetime.now(UTC),
        )
