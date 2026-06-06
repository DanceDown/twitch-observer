"""Runtime pattern matching for incoming Twitch chat messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord

from src.database.connection import (
    ChannelRepository,
    MessageRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRepository,
    TrackedUserRepository,
)
from src.events.event_types import TwitchChatMessageEvent
from src.localization import Localizer
from src.services.chat import ChatPatternMatcher
from src.services.twitch_gateways import TwitchUserLookup
from src.services.twitch_runtime import safe_get_twitch_user_by_id, safe_get_twitch_user_by_login
from src.utils.discord_embeds import build_tracking_embed

if TYPE_CHECKING:
    from src.services.chat import ChatPatternMatch

logger = logging.getLogger(__name__)


class TrackingNotificationSender:
    """Interface used by the tracking service to emit Discord embeds."""

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed: discord.Embed,
        *,
        channel_login: str | None = None,
    ) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass(slots=True)
class PatternTrackingService:
    """Evaluate incoming Twitch messages against stored ping/regex definitions."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    message_repository: MessageRepository
    twitch_api: TwitchUserLookup
    notifier: TrackingNotificationSender
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    tracked_user_repository: TrackedUserRepository | None = None
    reply_repository: ReplyRepository | None = None
    matcher: ChatPatternMatcher | None = None

    def __post_init__(self) -> None:
        if self.matcher is None:
            self.matcher = ChatPatternMatcher(
                thread_repository=self.thread_repository,
                channel_repository=self.channel_repository,
                pattern_repository=self.pattern_repository,
                reply_repository=self.reply_repository,
                tracked_user_repository=self.tracked_user_repository,
            )

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Check all interested Discord channels for pattern matches."""
        logger.debug(
            "Evaluating incoming Twitch message channel=%s broadcaster_id=%s author=%s author_id=%s content=%r",
            event.channel_login,
            event.broadcaster_id,
            event.author_login,
            event.author_id,
            event.content,
        )
        if not event.broadcaster_id:
            logger.warning(
                "Skipping Twitch message in #%s because Twitch IRC room-id is missing; pattern matching needs channel metadata.",
                event.channel_login,
            )
            return
        if not event.author_id:
            logger.warning(
                "Skipping Twitch message in #%s from %s because Twitch IRC user-id is missing; pattern matching needs author metadata.",
                event.channel_login,
                event.author_login,
            )
            return

        matches = await self.matcher.find_matches(event)
        if not matches:
            logger.debug("No tracking match produced for broadcaster_id=%s", event.broadcaster_id)
            return

        for match in matches:
            if match.reply is not None:
                logger.debug(
                    "Pattern %s matched for thread_id=%s but notification is delegated to auto-reply handling.",
                    match.pattern.pattern_id,
                    match.thread.thread_id,
                )
                continue
            await self.handle_match(event, match)

    async def handle_match(self, event: TwitchChatMessageEvent, match: ChatPatternMatch) -> None:
        """Send the Discord tracking notification for one prepared match."""
        author_user = await safe_get_twitch_user_by_login(
            self.twitch_api,
            event.author_login,
        )
        channel_user = await safe_get_twitch_user_by_id(
            self.twitch_api,
            event.broadcaster_id,
        )
        logger.info(
            "Pattern %s matched. Sending tracking embed to discord_channel_id=%s",
            match.pattern.pattern_id,
            match.thread.discord_channel_id,
        )
        await self.message_repository.mark_message_matched_in_thread(thread_id=match.thread.thread_id, event=event)
        await self.notifier.send_tracking_embed(
            match.thread.discord_channel_id,
            build_tracking_embed(
                event=event,
                pattern=match.pattern,
                thread=match.thread,
                localizer=self.localizer,
                channel=match.source_channel,
                author_icon_url=(None if author_user is None else author_user.profile_image_url),
                channel_display_name=(None if channel_user is None else channel_user.display_name),
            ),
            channel_login=None if channel_user is None else channel_user.login,
        )
