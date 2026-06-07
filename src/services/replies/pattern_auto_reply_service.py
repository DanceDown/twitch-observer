"""Runtime execution of pattern-bound Twitch auto-replies."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.database.connection import (
    ChannelRecord,
    ChannelRepository,
    MessageRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
)
from src.discord_results import build_result
from src.events.discord_results import DiscordResultStyle
from src.events.twitch_events import TwitchChatMessageEvent
from src.gateways.twitch_api import TwitchAPIError, TwitchAuthenticationError
from src.localization import Localizer
from src.services.account_support import AccountNotificationSender
from src.services.chat import ChatPatternMatcher
from src.services.patterns import TrackingNotificationSender
from src.services.twitch_gateways import TwitchReplyGateway
from src.services.twitch_runtime import (
    ensure_fresh_linked_account,
    refresh_linked_account,
    safe_get_twitch_user_by_id,
    safe_get_twitch_user_by_login,
)
from src.utils.discord_embeds import build_auto_reply_embed

if TYPE_CHECKING:
    from src.services.chat import ChatPatternMatch

logger = logging.getLogger(__name__)


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
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    matcher: ChatPatternMatcher | None = None
    handled_messages: int = field(default=0, init=False)
    sent_replies: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.matcher is None:
            self.matcher = ChatPatternMatcher(pattern_repository=self.pattern_repository)

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
        account = (
            await self.account_repository.get_by_account_id(match.thread.account_id)
            if match.thread.account_id is not None
            else None
        )
        if account is None or not account.access_token:
            logger.debug(
                "Skipping auto-replies for thread_id=%s because no account is linked.",
                match.thread.thread_id,
            )
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
        )
        rendered_reply_message = self._render_reply_message(
            matching_reply.reply_message,
            event,
            channel_name=(None if channel_user is None else channel_user.display_name),
        )

        try:
            account = (
                await ensure_fresh_linked_account(
                    account=account,
                    account_repository=self.account_repository,
                    twitch_auth=self.twitch_api,
                    token_refresh_skew_seconds=self.token_refresh_skew_seconds,
                    thread_repository=self.thread_repository,
                    thread=match.thread,
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
                match.thread.thread_id,
                match.pattern.pattern_id,
                event.broadcaster_id,
                account.twitch_user_id,
            )
            author_user = await safe_get_twitch_user_by_login(
                self.twitch_api,
                event.author_login,
            )
            await self._notify_auto_reply(
                thread=match.thread,
                event=event,
                pattern=match.pattern,
                reply=ReplyRecord(
                    thread_id=matching_reply.thread_id,
                    pattern_id=matching_reply.pattern_id,
                    reply_message=rendered_reply_message,
                    reply_as_reply=matching_reply.reply_as_reply,
                    disabled=matching_reply.disabled,
                ),
                source_channel=match.source_channel,
                author_icon_url=(None if author_user is None else author_user.profile_image_url),
                channel_display_name=(None if channel_user is None else channel_user.display_name),
                channel_login=None if channel_user is None else channel_user.login,
            )
        except TwitchAuthenticationError as error:
            refreshed = await refresh_linked_account(
                account=account,
                account_repository=self.account_repository,
                twitch_auth=self.twitch_api,
                thread_repository=self.thread_repository,
                thread=match.thread,
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
                        match.thread.thread_id,
                        match.pattern.pattern_id,
                        event.broadcaster_id,
                        refreshed.twitch_user_id,
                    )
                    author_user = await safe_get_twitch_user_by_login(
                        self.twitch_api,
                        event.author_login,
                    )
                    await self._notify_auto_reply(
                        thread=match.thread,
                        event=event,
                        pattern=match.pattern,
                        reply=ReplyRecord(
                            thread_id=matching_reply.thread_id,
                            pattern_id=matching_reply.pattern_id,
                            reply_message=rendered_reply_message,
                            reply_as_reply=matching_reply.reply_as_reply,
                            disabled=matching_reply.disabled,
                        ),
                        source_channel=match.source_channel,
                        author_icon_url=(None if author_user is None else author_user.profile_image_url),
                        channel_display_name=(None if channel_user is None else channel_user.display_name),
                        channel_login=(None if channel_user is None else channel_user.login),
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
        except TwitchAPIError as error:
            logger.warning(
                "Failed to send auto-reply thread_id=%s pattern_id=%s: %s",
                match.thread.thread_id,
                match.pattern.pattern_id,
                error,
            )

    async def _notify_auto_reply(
        self,
        *,
        thread: ThreadRecord,
        event: TwitchChatMessageEvent,
        pattern: PatternRecord,
        reply: ReplyRecord,
        source_channel: ChannelRecord | None,
        author_icon_url: str | None = None,
        channel_display_name: str | None = None,
        channel_login: str | None = None,
    ) -> None:
        await self.tracking_notifier.send_tracking_embed(
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
        channel_name: str | None = None,
    ) -> str:
        """Expand reply placeholders using the matched Twitch chat message."""
        rendered = template.replace("{NAME}", event.author_display_name or event.author_login)
        rendered = rendered.replace("{CHANNEL}", channel_name or event.channel_login)
        return rendered.replace("{MESSAGE}", event.content)

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
