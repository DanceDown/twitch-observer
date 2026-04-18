from __future__ import annotations

"""Business logic for managing and executing Twitch auto-replies."""

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
import logging

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError, TwitchAuthenticationError
from src.database.connection import (
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    TrackedUserRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordReplyRequestedEvent,
    DiscordResultStyle,
    EventType,
    TwitchChatMessageEvent,
)
from src.services.authz import thread_has_permission
from src.utils.pattern_matching import matches_pattern
from src.utils.discord_embeds import build_auto_reply_embed, escape_discord_preserving_links
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReplyCommandService:
    """Handle `/reply` add/remove/disable/enable requests for pattern-bound auto-replies."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    account_repository: TwitchAccountRepository
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_REPLY_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordReplyRequestedEvent) -> None:
        try:
            result = self._handle_action(event)
        except ValueError as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not event.result_future.done():
            event.result_future.set_result(result)

    def _handle_action(self, event: DiscordReplyRequestedEvent) -> DiscordCommandResult:
        if event.action in {"add", "remove"}:
            required_permission = ObserverPermission.MANAGE_REPLIES
            denial_message = "You do not have permission to add or remove auto-replies in this Discord channel."
        else:
            required_permission = ObserverPermission.TOGGLE_REPLIES
            denial_message = "You do not have permission to enable or disable auto-replies in this Discord channel."

        thread = self._ensure_thread_permission(
            event.discord_channel_id,
            event.requester_id,
            required_permission=required_permission,
            denial_message=denial_message,
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        pattern = self.pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, p_index=event.pattern_id)
        if pattern is None:
            return DiscordCommandResult(
                title="Pattern Not Found",
                message="No ping or regex rule with that ID exists.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if event.action == "add":
            linked_account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
            if linked_account is None:
                return DiscordCommandResult(
                    title="No Linked Account",
                    message="This Discord channel must link a Twitch account first with `/account link` before auto-replies can be enabled.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )

            message = (event.message or "").strip()
            if not message:
                raise ValueError("Please provide the reply message.")
            if len(message) > 500:
                raise ValueError("Twitch chat messages are limited to 500 characters.")
            existing_reply = self.reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=pattern.p_index)
            if existing_reply is not None:
                return DiscordCommandResult(
                    title="Reply Already Exists",
                    message=(
                        "This pattern already has an attached auto-reply. "
                        "Remove it first before creating a new one."
                    ),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )

            created = self.reply_repository.add_reply(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
                reply_message=message,
                reply_as_reply=event.reply_as_reply,
            )
            assert created is not None
            return DiscordCommandResult(
                title="Auto-Reply Added",
                message=(
                    f"Added an auto-reply to pattern #{pattern.p_index}.\n"
                    f"Mode: {'Reply to the matched message' if created.reply_as_reply else 'Send a separate Twitch message'}\n"
                    f"Message: {escape_discord_preserving_links(created.reply_message)}"
                ),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "remove":
            existing_reply = self.reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=pattern.p_index)
            if existing_reply is None:
                return DiscordCommandResult(
                    title="No Auto-Reply Configured",
                    message="This pattern does not have an auto-reply.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            cleared = self.reply_repository.remove_reply(thread_id=thread.thread_id, p_index=pattern.p_index)
            assert cleared is not None
            return DiscordCommandResult(
                title="Auto-Reply Removed",
                message=f"Removed the auto-reply from pattern `{pattern.p_index}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "disable":
            existing_reply = self.reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=pattern.p_index)
            if existing_reply is None:
                return DiscordCommandResult(
                    title="No Auto-Reply Configured",
                    message="This pattern does not have an auto-reply.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            if existing_reply.disabled:
                return DiscordCommandResult(
                    title="Already Disabled",
                    message="This auto-reply is already disabled.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            disabled_reply = self.reply_repository.set_reply_disabled(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
                disabled=True,
            )
            assert disabled_reply is not None
            return DiscordCommandResult(
                title="Auto-Reply Disabled",
                message=f"Disabled the auto-reply on pattern `{pattern.p_index}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "enable":
            existing_reply = self.reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=pattern.p_index)
            if existing_reply is None:
                return DiscordCommandResult(
                    title="No Auto-Reply Configured",
                    message="This pattern does not have an auto-reply.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            if not existing_reply.disabled:
                return DiscordCommandResult(
                    title="Already Enabled",
                    message="This auto-reply is already enabled.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            enabled_reply = self.reply_repository.set_reply_disabled(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
                disabled=False,
            )
            assert enabled_reply is not None
            return DiscordCommandResult(
                title="Auto-Reply Enabled",
                message=f"Enabled the auto-reply on pattern `{pattern.p_index}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        raise ValueError("Unsupported reply action. Use add, remove, disable or enable.")

    def _ensure_thread_permission(
        self,
        discord_channel_id: int,
        requester_id: int,
        *,
        required_permission: ObserverPermission,
        denial_message: str,
    ) -> ThreadRecord | DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(discord_channel_id)
        if thread is None:
            return DiscordCommandResult(
                title="Not Joined",
                message="This Discord channel is not connected yet. Use `/join` first.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=requester_id,
            permission_repository=self.permission_repository,
            required_permission=required_permission,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message=denial_message,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread


@dataclass(slots=True)
class AutoReplyService:
    """Send Twitch chat replies for matching patterns that have a reply attached."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    account_repository: TwitchAccountRepository
    twitch_api: TwitchAPIClient
    tracked_user_repository: TrackedUserRepository | None = None
    notifier: object | None = None
    handled_messages: int = field(default=0, init=False)
    sent_replies: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, self.handle_chat_message)

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
            logger.debug("Skipping auto-replies because broadcaster_id or author_id is missing.")
            return

        thread_ids = self.channel_repository.list_thread_ids_by_twitch_channel_id(event.broadcaster_id)
        if not thread_ids:
            logger.debug("No configured threads for broadcaster_id=%s when evaluating auto-replies.", event.broadcaster_id)
            return

        live_status: bool | None = None
        for thread_id in thread_ids:
            thread = self.thread_repository.get_by_thread_id(thread_id)
            if thread is None:
                logger.debug("Skipping missing thread_id=%s during auto-reply evaluation.", thread_id)
                continue
            if not thread.enabled:
                logger.debug("Skipping disabled thread_id=%s during auto-reply evaluation.", thread.thread_id)
                continue

            account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
            if account is None or not account.access_token:
                logger.debug("Skipping auto-replies for thread_id=%s because no account is linked.", thread.thread_id)
                continue
            author_user = await self._safe_get_user_by_login(event.author_login)
            channel_user = await self._safe_get_user_by_id(event.broadcaster_id)
            match = await self._find_matching_reply_pattern(thread, event, live_status, account.twitch_user_id)
            if match is None:
                logger.debug("No reply-enabled pattern matched for thread_id=%s.", thread.thread_id)
                continue
            matching_pattern, matching_reply = match
            rendered_reply_message = self._render_reply_message(matching_reply.reply_message, event)

            try:
                account = await self._ensure_account_token(account)
                await self.twitch_api.send_chat_message(
                    access_token=account.access_token,
                    client_id=account.client_id,
                    sender_id=account.twitch_user_id,
                    broadcaster_id=event.broadcaster_id,
                    message=rendered_reply_message,
                    reply_parent_message_id=event.message_id if matching_reply.reply_as_reply else None,
                )
                self.sent_replies += 1
                logger.debug(
                    "Sent auto-reply thread_id=%s pattern_id=%s broadcaster_id=%s sender_id=%s",
                    thread.thread_id,
                    matching_pattern.p_index,
                    event.broadcaster_id,
                    account.twitch_user_id,
                )
                await self._notify_auto_reply(
                    thread=thread,
                    event=event,
                    pattern=matching_pattern,
                    author_icon_url=None if author_user is None else author_user.profile_image_url,
                    channel_display_name=None if channel_user is None else channel_user.display_name,
                    channel_login=None if channel_user is None else channel_user.login,
                    reply=ReplyRecord(
                        thread_id=matching_reply.thread_id,
                        p_index=matching_reply.p_index,
                        reply_message=rendered_reply_message,
                        reply_as_reply=matching_reply.reply_as_reply,
                        disabled=matching_reply.disabled,
                    ),
                )
            except TwitchAuthenticationError as error:
                refreshed = await self._try_refresh_account(account)
                if refreshed is not None:
                    try:
                        await self.twitch_api.send_chat_message(
                            access_token=refreshed.access_token,
                            client_id=refreshed.client_id,
                            sender_id=refreshed.twitch_user_id,
                            broadcaster_id=event.broadcaster_id,
                            message=rendered_reply_message,
                            reply_parent_message_id=event.message_id if matching_reply.reply_as_reply else None,
                        )
                        self.sent_replies += 1
                        logger.debug(
                            "Sent auto-reply after token refresh thread_id=%s pattern_id=%s broadcaster_id=%s sender_id=%s",
                            thread.thread_id,
                            matching_pattern.p_index,
                            event.broadcaster_id,
                            refreshed.twitch_user_id,
                        )
                        await self._notify_auto_reply(
                            thread=thread,
                            event=event,
                            pattern=matching_pattern,
                            author_icon_url=None if author_user is None else author_user.profile_image_url,
                            channel_display_name=None if channel_user is None else channel_user.display_name,
                            channel_login=None if channel_user is None else channel_user.login,
                            reply=ReplyRecord(
                                thread_id=matching_reply.thread_id,
                                p_index=matching_reply.p_index,
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
                            matching_pattern.p_index,
                            retry_error,
                        )
                if thread.account_id is not None:
                    self.account_repository.remove_by_account_id(thread.account_id)
                    self.thread_repository.set_account_id(discord_channel_id=thread.discord_channel_id, account_id=None)
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
                    matching_pattern.p_index,
                    error,
                )

    async def _find_matching_reply_pattern(
        self,
        thread: ThreadRecord,
        event: TwitchChatMessageEvent,
        live_status: bool | None,
        linked_twitch_user_id: str,
    ) -> tuple[PatternRecord, ReplyRecord] | None:
        for pattern in self.pattern_repository.list_active_patterns_for_thread(thread.thread_id):
            effective_pattern = self._expand_all_tracked_users(thread.thread_id, pattern)
            if not matches_pattern(effective_pattern, event):
                logger.debug("Pattern %s did not match incoming message for auto-reply evaluation.", effective_pattern.p_index)
                continue
            if (
                event.author_id == linked_twitch_user_id
                and effective_pattern.user_scope_mode != "only_selected"
            ):
                logger.debug(
                    "Skipping self-triggered auto-reply for pattern %s because user_scope_mode=%s is not self-explicit.",
                    effective_pattern.p_index,
                    effective_pattern.user_scope_mode,
                )
                continue
            current_live_status = live_status
            if effective_pattern.offline_state != "both":
                if current_live_status is None and event.broadcaster_id:
                    current_live_status = await self.twitch_api.is_user_live(event.broadcaster_id)
                if not self._offline_state_allows(effective_pattern, current_live_status):
                    logger.debug(
                        "Pattern %s matched text but was filtered by offline_state=%s live_status=%s during auto-reply evaluation.",
                        effective_pattern.p_index,
                        effective_pattern.offline_state,
                        current_live_status,
                    )
                    continue
            reply = self.reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=effective_pattern.p_index)
            if reply is None or reply.disabled:
                logger.debug("Pattern %s matched first but has no enabled auto-reply attached.", effective_pattern.p_index)
                return None
            return effective_pattern, reply
        return None

    def _expand_all_tracked_users(self, thread_id: int, pattern: PatternRecord) -> PatternRecord:
        if pattern.user_scope_mode not in {"all_tracked", "all_tracked_except_selected"}:
            return pattern
        if self.tracked_user_repository is None:
            tracked_user_ids: tuple[str, ...] = ()
        else:
            tracked_user_ids = tuple(user.twitch_user_id for user in self.tracked_user_repository.list_users_for_thread(thread_id))
        if pattern.user_scope_mode == "all_tracked_except_selected":
            tracked_user_ids = tuple(
                user_id for user_id in tracked_user_ids if user_id not in set(pattern.user_scope_ids)
            )
        return PatternRecord(
            thread_id=pattern.thread_id,
            p_index=pattern.p_index,
            regex=pattern.regex,
            channel_scope_mode=pattern.channel_scope_mode,
            channel_scope_ids=pattern.channel_scope_ids,
            user_scope_mode="only_selected",
            user_scope_ids=tracked_user_ids,
            sub_state=pattern.sub_state,
            offline_state=pattern.offline_state,
            is_regex=pattern.is_regex,
            case_sensitive=pattern.case_sensitive,
            color=pattern.color,
            disabled=pattern.disabled,
            notify=pattern.notify,
            priority=pattern.priority,
            reply_message=pattern.reply_message,
            reply_as_reply=pattern.reply_as_reply,
        )

    async def _ensure_account_token(self, account):
        if account.expires_at is None:
            return account
        try:
            expires_at = datetime.fromisoformat(account.expires_at)
        except ValueError:
            return account
        if expires_at > datetime.now(timezone.utc) + timedelta(seconds=30):
            return account
        refreshed = await self._try_refresh_account(account)
        return refreshed or account

    async def _try_refresh_account(self, account):
        if not account.refresh_token:
            return None
        try:
            refreshed = await self.twitch_api.refresh_user_access_token(account.refresh_token)
            validated = await self.twitch_api.validate_user_access_token(refreshed.access_token)
        except TwitchAPIError as error:
            logger.warning("Failed to refresh Twitch account for account_id=%s: %s", account.account_id, error)
            return None

        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=refreshed.expires_in)).isoformat()
        stored = self.account_repository.update_account(
            account_id=account.account_id,
            twitch_user_id=validated.user_id,
            twitch_login=validated.login,
            client_id=validated.client_id,
            access_token=refreshed.access_token,
            refresh_token=refreshed.refresh_token,
            expires_at=expires_at,
            scope=refreshed.scope,
            token_type=refreshed.token_type,
        )
        if stored is None:
            return None
        logger.debug("Refreshed Twitch account token for account_id=%s twitch_login=%s", stored.account_id, stored.twitch_login)
        return stored

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
        sender = getattr(self.notifier, "send_tracking_embed", None)
        if sender is None:
            return
        source_channel = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, event.broadcaster_id or "")
        await sender(
            thread.discord_channel_id,
            build_auto_reply_embed(
                event=event,
                pattern=pattern,
                thread=thread,
                reply=reply,
                channel=source_channel,
                author_icon_url=author_icon_url,
                channel_display_name=channel_display_name,
            ),
            channel_login=channel_login,
        )

    @staticmethod
    def _render_reply_message(template: str, event: TwitchChatMessageEvent) -> str:
        """Expand reply placeholders using the matched Twitch chat message."""
        rendered = template.replace("{NAME}", event.author_display_name or event.author_login)
        rendered = rendered.replace("{CHANNEL}", event.channel_login)
        rendered = rendered.replace("{MESSAGE}", event.content)
        return rendered

    async def _notify_account_expired(self, discord_channel_id: int) -> None:
        sender = getattr(self.notifier, "send_account_result", None)
        if sender is None:
            return
        await sender(
            0,
            discord_channel_id,
            DiscordCommandResult(
                title="Twitch Account Expired",
                message=(
                    "The linked Twitch account is no longer valid and must be linked again with `/account link`. "
                    "Existing auto-replies were kept and will work again after the account is reconnected."
                ),
                style=DiscordResultStyle.ERROR,
                ephemeral=False,
            ),
        )

    async def _safe_get_user_by_login(self, login: str):
        try:
            return await self.twitch_api.get_user_by_login(login)
        except Exception:
            return None

    async def _safe_get_user_by_id(self, user_id: str | None):
        if not user_id:
            return None
        try:
            return await self.twitch_api.get_user_by_id(user_id)
        except Exception:
            return None

    @staticmethod
    def _offline_state_allows(pattern: PatternRecord, live_status: bool | None) -> bool:
        if pattern.offline_state == "both" or live_status is None:
            return True
        if pattern.offline_state == "online":
            return live_status
        if pattern.offline_state == "offline":
            return not live_status
        return False
