"""Runtime execution of live/offline event auto-replies."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.gateways.twitch_api import TwitchAPIError, TwitchAuthenticationError
from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRepository,
    ThreadRepository,
    TwitchAccountRepository,
)
from src.events.event_types import (
    TwitchChannelLiveStateChangedEvent,
)
from src.services.twitch_gateways import TwitchReplyGateway
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    STREAM_EVENT_KEY_TO_STATE,
    STREAM_OFFLINE_EVENT_KEY,
    STREAM_ONLINE_EVENT_KEY,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
    ensure_fresh_linked_account,
    refresh_linked_account,
    safe_get_twitch_user_by_id,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChannelEventAutoReplyService:
    """Send Twitch messages when a tracked channel goes live or offline."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    adapter_event_repository: AdapterEventRepository
    adapter_event_action_repository: AdapterEventActionRepository
    account_repository: TwitchAccountRepository
    twitch_api: TwitchReplyGateway
    token_refresh_skew_seconds: int
    notifier: object | None = None

    async def handle_channel_live_state_changed(
        self,
        event: TwitchChannelLiveStateChangedEvent,
    ) -> None:
        event_key = STREAM_ONLINE_EVENT_KEY if event.is_live else STREAM_OFFLINE_EVENT_KEY
        configured_events = self.adapter_event_repository.list_matching_events(
            adapter_key=TWITCH_ADAPTER_KEY,
            subject_type=CHANNEL_SUBJECT_TYPE,
            subject_id=event.twitch_channel_id,
            event_key=event_key,
            include_disabled=False,
        )
        if not configured_events:
            return

        channel_user = await safe_get_twitch_user_by_id(
            self.twitch_api,
            event.twitch_channel_id,
        )
        channel_login = event.twitch_channel_login or (None if channel_user is None else channel_user.login)
        channel_name = (event.twitch_channel_login if channel_user is None else channel_user.display_name) or event.twitch_channel_id
        event_state = STREAM_EVENT_KEY_TO_STATE[event_key]
        for configured_event in configured_events:
            reply = self.adapter_event_action_repository.get_action(
                event_id=configured_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
            )
            if reply is None or reply.disabled or not reply.message_template:
                continue
            thread = self.thread_repository.get_by_thread_id(configured_event.thread_id)
            if thread is None or not thread.enabled:
                continue
            account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
            if account is None or not account.access_token:
                continue
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
                await self.twitch_api.send_chat_message(
                    access_token=account.access_token,
                    client_id=account.client_id,
                    sender_id=account.twitch_user_id,
                    broadcaster_id=event.twitch_channel_id,
                    message=rendered_message,
                )
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
                await self.twitch_api.send_chat_message(
                    access_token=refreshed.access_token,
                    client_id=refreshed.client_id,
                    sender_id=refreshed.twitch_user_id,
                    broadcaster_id=event.twitch_channel_id,
                    message=rendered_message,
                )
            except TwitchAPIError as error:
                logger.warning(
                    "Failed to send channel-event auto-reply thread_id=%s twitch_channel_id=%s state=%s channel_login=%s: %s",
                    configured_event.thread_id,
                    event.twitch_channel_id,
                    event_state,
                    channel_login,
                    error,
                )

    @staticmethod
    def _render_channel_event_reply(
        template: str,
        *,
        channel_name: str,
        state: str,
    ) -> str:
        rendered = template.replace("{CHANNEL}", channel_name)
        return rendered.replace("{STATE}", state)
