"""Runtime execution of pattern-bound Twitch auto-replies."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.database.connection import (
    ChannelRepository,
    MessageRepository,
    PatternRepository,
    ReplyRecord,
    ThreadRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
)
from src.discord_results import build_result
from src.events.discord_results import DiscordResultStyle
from src.events.twitch_events import TwitchChatMessageEvent, TwitchChatSendRequest
from src.gateways.twitch_api import TwitchAPIError, TwitchAuthenticationError, TwitchUser
from src.localization import Localizer
from src.services.account_support import AccountNotificationSender
from src.services.chat import ChatPatternMatcher
from src.services.patterns import TrackingNotificationSender
from src.services.twitch_gateways import TwitchReplyGateway
from src.services.twitch_runtime import (
    LinkedTwitchAccountRefreshContext,
    ensure_fresh_linked_account,
    refresh_linked_account,
    safe_get_twitch_user_by_id,
    safe_get_twitch_user_by_login,
)
from src.utils.discord_embeds import TrackingEmbedRequest, build_auto_reply_embed, build_tracking_embed

if TYPE_CHECKING:
    from src.services.chat import ChatPatternMatch

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _PatternAutoReplyDelivery:
    event: TwitchChatMessageEvent
    match: ChatPatternMatch
    matching_reply: ReplyRecord
    rendered_message: str
    account: TwitchAccountRecord
    channel_user: TwitchUser | None


@dataclass(slots=True)
class AutoReplyService:
    """Send Twitch chat replies for matching patterns that have a reply attached."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    message_repository: MessageRepository
    account_repository: TwitchAccountRepository
    twitch_api: TwitchReplyGateway
    token_refresh_skew_seconds: int
    tracking_notifier: TrackingNotificationSender
    account_notifier: AccountNotificationSender
    metadata_lookup_timeout_seconds: float | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    matcher: ChatPatternMatcher | None = None
    handled_messages: int = field(default=0, init=False)
    sent_replies: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Create the shared matcher when the caller did not inject one."""
        if self.matcher is None:
            self.matcher = ChatPatternMatcher(pattern_repository=self.pattern_repository)

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Evaluate one Twitch chat message for auto-reply matches."""
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

        matches = await self.matcher.find_matches(event)
        if not matches:
            logger.debug(
                "No configured threads for broadcaster_id=%s when evaluating auto-replies.",
                event.broadcaster_id,
            )
            return

        for match in matches:
            if match.reply is None:
                continue
            await self.handle_match(event, match)

    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        """Send one prepared Twitch auto-reply match."""
        matching_reply = match.reply
        if matching_reply is None:
            return
        account = await self.account_repository.get_by_account_id(match.thread.account_id) if match.thread.account_id is not None else None
        if account is None or not account.access_token:
            logger.debug(
                "Skipping auto-replies for thread_id=%s because no account is linked.",
                match.thread.thread_id,
            )
            await self._notify_tracking_fallback(event=event, match=match, already_marked=False)
            return
        if event.author_id == account.twitch_user_id and not match.explicit_user_scope_match:
            logger.debug(
                "Skipping self-triggered auto-reply for pattern %s because the match was not user-explicit.",
                match.pattern.pattern_id,
            )
            return

        await self.message_repository.mark_message_matched_in_thread(thread_id=match.thread.thread_id, event=event)
        channel_user = await safe_get_twitch_user_by_id(
            self.twitch_api,
            event.broadcaster_id,
            timeout_seconds=self.metadata_lookup_timeout_seconds,
        )
        rendered_reply_message = self._render_reply_message(
            matching_reply.reply_message,
            event,
            channel_name=(None if channel_user is None else channel_user.display_name),
        )

        try:
            refresh_context = LinkedTwitchAccountRefreshContext(
                account_repository=self.account_repository,
                twitch_auth=self.twitch_api,
                thread_repository=self.thread_repository,
                thread=match.thread,
            )
            account = (
                await ensure_fresh_linked_account(
                    account=account,
                    context=refresh_context,
                    token_refresh_skew_seconds=self.token_refresh_skew_seconds,
                )
                or account
            )
            await self._send_reply_and_notify(
                _PatternAutoReplyDelivery(
                    event=event,
                    match=match,
                    matching_reply=matching_reply,
                    rendered_message=rendered_reply_message,
                    account=account,
                    channel_user=channel_user,
                )
            )
        except TwitchAuthenticationError as error:
            refreshed = await refresh_linked_account(
                account=account,
                context=refresh_context,
            )
            if refreshed is not None:
                try:
                    await self._send_reply_and_notify(
                        _PatternAutoReplyDelivery(
                            event=event,
                            match=match,
                            matching_reply=matching_reply,
                            rendered_message=rendered_reply_message,
                            account=refreshed,
                            channel_user=channel_user,
                        )
                    )
                    return
                except TwitchAPIError as retry_error:
                    logger.warning(
                        "Failed to send auto-reply after refresh thread_id=%s pattern_id=%s: %s",
                        match.thread.thread_id,
                        match.pattern.pattern_id,
                        retry_error,
                    )
            if match.thread.account_id is not None:
                await self.account_repository.remove_by_account_id(match.thread.account_id)
                await self.thread_repository.set_account_id(
                    discord_channel_id=match.thread.discord_channel_id,
                    account_id=None,
                )
            logger.warning(
                "Removed invalid linked Twitch account for thread_id=%s after auth failure. Error: %s",
                match.thread.thread_id,
                error,
            )
            await self._notify_account_expired(match.thread.discord_channel_id)
            await self._notify_tracking_fallback(event=event, match=match, already_marked=True)
        except TwitchAPIError as error:
            logger.warning(
                "Failed to send auto-reply thread_id=%s pattern_id=%s: %s",
                match.thread.thread_id,
                match.pattern.pattern_id,
                error,
            )
            await self._notify_tracking_fallback(event=event, match=match, already_marked=True)

    async def reserve_match_delivery(self, match: ChatPatternMatch) -> None:
        """Reserve ordered Discord delivery for the eventual reply notification."""
        await self.tracking_notifier.reserve_tracking_delivery(thread_id=match.thread.thread_id)

    async def _send_reply_and_notify(self, delivery: _PatternAutoReplyDelivery) -> None:
        sent_message_id = await self.twitch_api.send_chat_message(
            TwitchChatSendRequest(
                access_token=delivery.account.access_token,
                client_id=delivery.account.client_id,
                sender_id=delivery.account.twitch_user_id,
                broadcaster_id=delivery.event.broadcaster_id,
                message=delivery.rendered_message,
                reply_parent_message_id=(delivery.event.message_id if delivery.matching_reply.reply_as_reply else None),
            )
        )
        sender_display_name = await self._resolve_account_display_name(delivery.account)
        await self.message_repository.save_bot_twitch_message(
            self._build_sent_message_event(
                delivery=delivery,
                message_id=sent_message_id,
                sender_display_name=sender_display_name,
            )
        )
        self.sent_replies += 1
        logger.debug(
            "Sent auto-reply thread_id=%s pattern_id=%s broadcaster_id=%s sender_id=%s",
            delivery.match.thread.thread_id,
            delivery.match.pattern.pattern_id,
            delivery.event.broadcaster_id,
            delivery.account.twitch_user_id,
        )
        author_user = await safe_get_twitch_user_by_login(
            self.twitch_api,
            delivery.event.author_login,
            timeout_seconds=self.metadata_lookup_timeout_seconds,
        )
        await self._notify_auto_reply(delivery, author_icon_url=None if author_user is None else author_user.profile_image_url)

    async def _notify_auto_reply(self, delivery: _PatternAutoReplyDelivery, *, author_icon_url: str | None = None) -> None:
        rendered_reply = ReplyRecord(
            thread_id=delivery.matching_reply.thread_id,
            pattern_id=delivery.matching_reply.pattern_id,
            reply_message=delivery.rendered_message,
            reply_as_reply=delivery.matching_reply.reply_as_reply,
            disabled=delivery.matching_reply.disabled,
        )
        await self.tracking_notifier.send_tracking_embed(
            delivery.match.thread.discord_channel_id,
            build_auto_reply_embed(
                TrackingEmbedRequest(
                    event=delivery.event,
                    pattern=delivery.match.pattern,
                    thread=delivery.match.thread,
                    localizer=self.localizer,
                    channel=delivery.match.source_channel,
                    reply=rendered_reply,
                    author_icon_url=author_icon_url,
                    channel_display_name=None if delivery.channel_user is None else delivery.channel_user.display_name,
                )
            ),
            channel_login=None if delivery.channel_user is None else delivery.channel_user.login,
            thread_id=delivery.match.thread.thread_id,
        )

    async def _notify_tracking_fallback(
        self,
        *,
        event: TwitchChatMessageEvent,
        match: ChatPatternMatch,
        already_marked: bool,
    ) -> None:
        if not already_marked:
            await self.message_repository.mark_message_matched_in_thread(thread_id=match.thread.thread_id, event=event)
        author_user, channel_user = await asyncio.gather(
            safe_get_twitch_user_by_login(
                self.twitch_api,
                event.author_login,
                timeout_seconds=self.metadata_lookup_timeout_seconds,
            ),
            safe_get_twitch_user_by_id(
                self.twitch_api,
                event.broadcaster_id,
                timeout_seconds=self.metadata_lookup_timeout_seconds,
            ),
        )
        await self.tracking_notifier.send_tracking_embed(
            match.thread.discord_channel_id,
            build_tracking_embed(
                TrackingEmbedRequest(
                    event=event,
                    pattern=match.pattern,
                    thread=match.thread,
                    localizer=self.localizer,
                    channel=match.source_channel,
                    author_icon_url=(None if author_user is None else author_user.profile_image_url),
                    channel_display_name=(None if channel_user is None else channel_user.display_name),
                )
            ),
            channel_login=None if channel_user is None else channel_user.login,
            thread_id=match.thread.thread_id,
        )

    @staticmethod
    def _render_reply_message(
        template: str,
        event: TwitchChatMessageEvent,
        channel_name: str | None = None,
    ) -> str:
        """Expand reply placeholders using the matched Twitch chat message."""
        rendered = template.replace("{NAME}", event.author_display_name or event.author_login)
        rendered = rendered.replace("{CHANNEL}", channel_name or event.channel_login)
        return rendered.replace("{MESSAGE}", event.content)

    @staticmethod
    def _build_sent_message_event(
        *,
        delivery: _PatternAutoReplyDelivery,
        message_id: str,
        sender_display_name: str,
    ) -> TwitchChatMessageEvent:
        return TwitchChatMessageEvent(
            channel_login=delivery.event.channel_login if delivery.channel_user is None else delivery.channel_user.login,
            author_login=delivery.account.twitch_login,
            author_display_name=sender_display_name,
            author_id=delivery.account.twitch_user_id,
            broadcaster_id=delivery.event.broadcaster_id,
            message_id=message_id,
            content=delivery.rendered_message,
            reply_parent_message_id=(delivery.event.message_id if delivery.matching_reply.reply_as_reply else None),
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

    async def _notify_account_expired(self, discord_channel_id: int) -> None:
        await self.account_notifier.send_account_result(
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
