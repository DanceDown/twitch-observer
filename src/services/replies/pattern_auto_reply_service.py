"""Runtime execution of pattern-bound Twitch auto-replies."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.gateways.twitch_api import TwitchAPIError, TwitchAuthenticationError
from src.database.connection import (
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
    TwitchAccountRepository,
)
from src.discord_results import build_result
from src.events.event_types import (
    DiscordResultStyle,
    TwitchChatMessageEvent,
)
from src.localization import Localizer
from src.services.account_service import AccountNotificationSender
from src.services.patterns import TrackingNotificationSender
from src.services.twitch_gateways import TwitchReplyGateway
from src.services.twitch_runtime import (
    ensure_fresh_linked_account,
    expand_pattern_for_tracked_users,
    offline_state_allows,
    refresh_linked_account,
    safe_get_twitch_user_by_id,
    safe_get_twitch_user_by_login,
)
from src.utils.discord_embeds import build_auto_reply_embed
from src.utils.pattern_matching import matches_pattern

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AutoReplyService:
    """Send Twitch chat replies for matching patterns that have a reply attached."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    account_repository: TwitchAccountRepository
    twitch_api: TwitchReplyGateway
    token_refresh_skew_seconds: int
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    tracked_user_repository: TrackedUserRepository | None = None
    notifier: TrackingNotificationSender | AccountNotificationSender | None = None
    handled_messages: int = field(default=0, init=False)
    sent_replies: int = field(default=0, init=False)

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        self.handled_messages += 1
        logger.debug(
            "Evaluating auto-replies channel=%s broadcaster_id=%s author=%s author_id=%s message_id=%s content=%r",
            event.channel_login,
            event.broadcaster_id,
            event.author_login,
            event.author_id,
            event.message_id,
            event.content,
        )
        if not event.broadcaster_id or not event.author_id:
            logger.debug(
                "Skipping auto-replies because broadcaster_id or author_id is missing.",
            )
            return

        thread_ids = self.channel_repository.list_thread_ids_by_twitch_channel_id(
            event.broadcaster_id,
        )
        if not thread_ids:
            logger.debug(
                "No configured threads for broadcaster_id=%s when evaluating auto-replies.",
                event.broadcaster_id,
            )
            return

        for thread_id in thread_ids:
            thread = self.thread_repository.get_by_thread_id(thread_id)
            if thread is None:
                logger.debug(
                    "Skipping missing thread_id=%s during auto-reply evaluation.",
                    thread_id,
                )
                continue
            if not thread.enabled:
                logger.debug(
                    "Skipping disabled thread_id=%s during auto-reply evaluation.",
                    thread.thread_id,
                )
                continue

            account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
            if account is None or not account.access_token:
                logger.debug(
                    "Skipping auto-replies for thread_id=%s because no account is linked.",
                    thread.thread_id,
                )
                continue
            source_channel = self.channel_repository.get_by_thread_and_twitch_channel(
                thread.thread_id,
                event.broadcaster_id,
            )
            live_status = None if source_channel is None else source_channel.is_live
            match = await self._find_matching_reply_pattern(
                thread,
                event,
                live_status,
                account.twitch_user_id,
            )
            if match is None:
                logger.debug(
                    "No reply-enabled pattern matched for thread_id=%s.",
                    thread.thread_id,
                )
                continue
            matching_pattern, matching_reply = match
            rendered_reply_message = self._render_reply_message(
                matching_reply.reply_message,
                event,
            )

            try:
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
                await self.twitch_api.send_chat_message(
                    access_token=account.access_token,
                    client_id=account.client_id,
                    sender_id=account.twitch_user_id,
                    broadcaster_id=event.broadcaster_id,
                    message=rendered_reply_message,
                    reply_parent_message_id=(event.message_id if matching_reply.reply_as_reply else None),
                )
                self.sent_replies += 1
                logger.debug(
                    "Sent auto-reply thread_id=%s pattern_id=%s broadcaster_id=%s sender_id=%s",
                    thread.thread_id,
                    matching_pattern.pattern_id,
                    event.broadcaster_id,
                    account.twitch_user_id,
                )
                author_user = await safe_get_twitch_user_by_login(
                    self.twitch_api,
                    event.author_login,
                )
                channel_user = await safe_get_twitch_user_by_id(
                    self.twitch_api,
                    event.broadcaster_id,
                )
                await self._notify_auto_reply(
                    thread=thread,
                    event=event,
                    pattern=matching_pattern,
                    author_icon_url=(None if author_user is None else author_user.profile_image_url),
                    channel_display_name=(None if channel_user is None else channel_user.display_name),
                    channel_login=None if channel_user is None else channel_user.login,
                    reply=ReplyRecord(
                        thread_id=matching_reply.thread_id,
                        pattern_id=matching_reply.pattern_id,
                        reply_message=rendered_reply_message,
                        reply_as_reply=matching_reply.reply_as_reply,
                        disabled=matching_reply.disabled,
                    ),
                )
            except TwitchAuthenticationError as error:
                refreshed = await refresh_linked_account(
                    account=account,
                    account_repository=self.account_repository,
                    twitch_auth=self.twitch_api,
                    thread_repository=self.thread_repository,
                    thread=thread,
                )
                if refreshed is not None:
                    try:
                        await self.twitch_api.send_chat_message(
                            access_token=refreshed.access_token,
                            client_id=refreshed.client_id,
                            sender_id=refreshed.twitch_user_id,
                            broadcaster_id=event.broadcaster_id,
                            message=rendered_reply_message,
                            reply_parent_message_id=(event.message_id if matching_reply.reply_as_reply else None),
                        )
                        self.sent_replies += 1
                        logger.debug(
                            "Sent auto-reply after token refresh thread_id=%s pattern_id=%s broadcaster_id=%s sender_id=%s",
                            thread.thread_id,
                            matching_pattern.pattern_id,
                            event.broadcaster_id,
                            refreshed.twitch_user_id,
                        )
                        author_user = await safe_get_twitch_user_by_login(
                            self.twitch_api,
                            event.author_login,
                        )
                        channel_user = await safe_get_twitch_user_by_id(
                            self.twitch_api,
                            event.broadcaster_id,
                        )
                        await self._notify_auto_reply(
                            thread=thread,
                            event=event,
                            pattern=matching_pattern,
                            author_icon_url=(None if author_user is None else author_user.profile_image_url),
                            channel_display_name=(None if channel_user is None else channel_user.display_name),
                            channel_login=(None if channel_user is None else channel_user.login),
                            reply=ReplyRecord(
                                thread_id=matching_reply.thread_id,
                                pattern_id=matching_reply.pattern_id,
                                reply_message=rendered_reply_message,
                                reply_as_reply=matching_reply.reply_as_reply,
                                disabled=matching_reply.disabled,
                            ),
                        )
                        continue
                    except TwitchAPIError as retry_error:
                        logger.warning(
                            "Failed to send auto-reply after refresh thread_id=%s pattern_id=%s: %s",
                            thread.thread_id,
                            matching_pattern.pattern_id,
                            retry_error,
                        )
                if thread.account_id is not None:
                    self.account_repository.remove_by_account_id(thread.account_id)
                    self.thread_repository.set_account_id(
                        discord_channel_id=thread.discord_channel_id,
                        account_id=None,
                    )
                logger.warning(
                    "Removed invalid linked Twitch account for thread_id=%s after auth failure. Error: %s",
                    thread.thread_id,
                    error,
                )
                await self._notify_account_expired(thread.discord_channel_id)
            except TwitchAPIError as error:
                logger.warning(
                    "Failed to send auto-reply thread_id=%s pattern_id=%s: %s",
                    thread.thread_id,
                    matching_pattern.pattern_id,
                    error,
                )

    async def _find_matching_reply_pattern(
        self,
        thread: ThreadRecord,
        event: TwitchChatMessageEvent,
        live_status: bool | None,
        linked_twitch_user_id: str,
    ) -> tuple[PatternRecord, ReplyRecord] | None:
        for pattern in self.pattern_repository.list_active_patterns_for_thread(
            thread.thread_id,
        ):
            effective_pattern = expand_pattern_for_tracked_users(
                pattern,
                thread_id=thread.thread_id,
                tracked_user_repository=self.tracked_user_repository,
            )
            if not matches_pattern(effective_pattern, event):
                logger.debug(
                    "Pattern %s did not match incoming message for auto-reply evaluation.",
                    effective_pattern.pattern_id,
                )
                continue
            if event.author_id == linked_twitch_user_id and effective_pattern.user_scope_mode != "only_selected":
                logger.debug(
                    "Skipping self-triggered auto-reply for pattern %s because user_scope_mode=%s is not self-explicit.",
                    effective_pattern.pattern_id,
                    effective_pattern.user_scope_mode,
                )
                continue
            current_live_status = live_status
            if effective_pattern.offline_state != "both" and not offline_state_allows(effective_pattern, current_live_status):
                logger.debug(
                    "Pattern %s matched text but was filtered by offline_state=%s live_status=%s during auto-reply evaluation.",
                    effective_pattern.pattern_id,
                    effective_pattern.offline_state,
                    current_live_status,
                )
                continue
            reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                pattern_id=effective_pattern.pattern_id,
            )
            if reply is None or reply.disabled:
                logger.debug(
                    "Pattern %s matched first but has no enabled auto-reply attached.",
                    effective_pattern.pattern_id,
                )
                return None
            return effective_pattern, reply
        return None

    async def _notify_auto_reply(
        self,
        *,
        thread: ThreadRecord,
        event: TwitchChatMessageEvent,
        pattern: PatternRecord,
        reply: ReplyRecord,
        author_icon_url: str | None = None,
        channel_display_name: str | None = None,
        channel_login: str | None = None,
    ) -> None:
        if self.notifier is None:
            return
        source_channel = self.channel_repository.get_by_thread_and_twitch_channel(
            thread.thread_id,
            event.broadcaster_id or "",
        )
        await self.notifier.send_tracking_embed(
            thread.discord_channel_id,
            build_auto_reply_embed(
                event=event,
                pattern=pattern,
                thread=thread,
                localizer=self.localizer,
                reply=reply,
                channel=source_channel,
                author_icon_url=author_icon_url,
                channel_display_name=channel_display_name,
            ),
            channel_login=channel_login,
        )

    @staticmethod
    def _render_reply_message(
        template: str,
        event: TwitchChatMessageEvent,
    ) -> str:
        """Expand reply placeholders using the matched Twitch chat message."""
        rendered = template.replace("{NAME}", event.author_display_name or event.author_login)
        rendered = rendered.replace("{CHANNEL}", event.channel_login)
        return rendered.replace("{MESSAGE}", event.content)

    async def _notify_account_expired(self, discord_channel_id: int) -> None:
        if self.notifier is None:
            return
        await self.notifier.send_account_result(
            0,
            discord_channel_id,
            build_result(
                self.localizer,
                "results.write.account_expired",
                language=self.localizer.default_language,
                style=DiscordResultStyle.ERROR,
                ephemeral=False,
            ),
        )
