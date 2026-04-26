from __future__ import annotations

"""Runtime pattern matching for incoming Twitch chat messages."""

import logging
from dataclasses import dataclass, field

import discord

from src.adapters.twitch_api import TwitchAPIClient
from src.database.connection import (
    ChannelRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRepository,
    TrackedUserRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import EventType, TwitchChatMessageEvent
from src.localization import Localizer
from src.services.twitch_runtime import (
    expand_pattern_for_tracked_users,
    offline_state_allows,
    safe_get_twitch_user_by_id,
    safe_get_twitch_user_by_login,
)
from src.utils.discord_embeds import build_tracking_embed
from src.utils.pattern_matching import matches_pattern

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

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchAPIClient
    notifier: TrackingNotificationSender
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    tracked_user_repository: TrackedUserRepository | None = None
    reply_repository: ReplyRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, self.handle_chat_message)

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Check all interested Discord channels for pattern matches."""
        logger.debug(
            "Evaluating incoming Twitch message channel=%s broadcaster_id=%s "
            "author=%s author_id=%s content=%r",
            event.channel_login,
            event.broadcaster_id,
            event.author_login,
            event.author_id,
            event.content,
        )
        if not event.broadcaster_id:
            logger.warning(
                "Skipping Twitch message in #%s because Twitch IRC room-id is missing; "
                "pattern matching needs channel metadata.",
                event.channel_login,
            )
            return
        if not event.author_id:
            logger.warning(
                "Skipping Twitch message in #%s from %s because Twitch IRC user-id is missing; "
                "pattern matching needs author metadata.",
                event.channel_login,
                event.author_login,
            )
            return

        thread_ids = self.channel_repository.list_thread_ids_by_twitch_channel_id(
            event.broadcaster_id,
        )
        if not thread_ids:
            logger.debug("No Discord threads track broadcaster_id=%s", event.broadcaster_id)
            return

        for thread_id in thread_ids:
            thread = self.thread_repository.get_by_thread_id(thread_id)
            if thread is None:
                logger.debug(
                    "Skipping missing thread_id=%s referenced by channel repository.",
                    thread_id,
                )
                continue
            if not thread.enabled:
                logger.debug(
                    "Skipping disabled thread_id=%s during tracking evaluation.",
                    thread.thread_id,
                )
                continue

            patterns = self.pattern_repository.list_active_patterns_for_thread(
                thread.thread_id,
            )
            logger.debug(
                "Thread %s has %d active pattern(s).",
                thread.thread_id,
                len(patterns),
            )
            source_channel = self.channel_repository.get_by_thread_and_twitch_channel(
                thread.thread_id,
                event.broadcaster_id,
            )
            live_status = None if source_channel is None else source_channel.is_live
            for pattern in patterns:
                effective_pattern = expand_pattern_for_tracked_users(
                    pattern,
                    thread_id=thread.thread_id,
                    tracked_user_repository=self.tracked_user_repository,
                )
                if not matches_pattern(effective_pattern, event):
                    logger.debug(
                        "Pattern %s did not match message. regex=%r channel_filter=%s "
                        "user_filter=%s sub=%s offline=%s is_regex=%s",
                        effective_pattern.p_index,
                        effective_pattern.regex,
                        effective_pattern.channel_scope_ids,
                        effective_pattern.user_scope_ids,
                        effective_pattern.sub_state,
                        effective_pattern.offline_state,
                        effective_pattern.is_regex,
                    )
                    continue
                if not offline_state_allows(effective_pattern, live_status):
                    logger.debug(
                        "Pattern %s matched text but was filtered by "
                        "offline_state=%s live_status=%s",
                        effective_pattern.p_index,
                        effective_pattern.offline_state,
                        live_status,
                    )
                    continue

                if self._has_enabled_reply(thread.thread_id, effective_pattern.p_index):
                    logger.debug(
                        "Pattern %s matched for thread_id=%s but notification is "
                        "delegated to auto-reply handling.",
                        effective_pattern.p_index,
                        thread.thread_id,
                    )
                    break

                author_user = await safe_get_twitch_user_by_login(
                    self.twitch_api,
                    event.author_login,
                )
                channel_user = await safe_get_twitch_user_by_id(
                    self.twitch_api,
                    event.broadcaster_id,
                )
                logger.info(
                    "Pattern %s matched. Sending tracking embed to "
                    "discord_channel_id=%s",
                    effective_pattern.p_index,
                    thread.discord_channel_id,
                )
                await self.notifier.send_tracking_embed(
                    thread.discord_channel_id,
                    build_tracking_embed(
                        event=event,
                        pattern=effective_pattern,
                        thread=thread,
                        localizer=self.localizer,
                        channel=source_channel,
                        author_icon_url=(
                            None if author_user is None else author_user.profile_image_url
                        ),
                        channel_display_name=(
                            None if channel_user is None else channel_user.display_name
                        ),
                    ),
                    channel_login=None if channel_user is None else channel_user.login,
                )
                break

    def _has_enabled_reply(self, thread_id: int, pattern_id: int) -> bool:
        if self.reply_repository is None:
            return False
        reply = self.reply_repository.get_by_pattern(
            thread_id=thread_id,
            p_index=pattern_id,
        )
        return reply is not None and not reply.disabled
