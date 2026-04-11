from __future__ import annotations

"""Business logic for manually sending Twitch chat messages from Discord."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError, TwitchAuthenticationError
from src.database.connection import ChannelRepository, ThreadRepository, TwitchAccountRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    DiscordWriteRequestedEvent,
    EventType,
)
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TwitchWriteCommandService:
    """Handle `/write` requests for manual Twitch chat output."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    account_repository: TwitchAccountRepository
    twitch_api: TwitchAPIClient
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_WRITE_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordWriteRequestedEvent) -> None:
        try:
            result = await self._send_message(event)
        except ValueError as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except TwitchAPIError as error:
            result = DiscordCommandResult(
                title="Twitch API Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling Twitch write command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _send_message(self, event: DiscordWriteRequestedEvent) -> DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if thread is None:
            return DiscordCommandResult(
                title="Not Joined",
                message="This Discord channel is not connected yet. Use `/join` first.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=event.requester_id,
            permission_repository=self.permission_repository,
            required_permission=ObserverPermission.SEND_TWITCH_MESSAGES,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message="You do not have permission to send Twitch chat messages from this Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        message = event.message.strip()
        if not message:
            raise ValueError("Please provide a non-empty Twitch chat message.")
        if len(message) > 500:
            raise ValueError("Twitch chat messages are limited to 500 characters.")

        twitch_channel = await self.twitch_api.get_user_by_login(event.twitch_channel_login)
        tracked_channel = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, twitch_channel.user_id)
        if tracked_channel is None:
            return DiscordCommandResult(
                title="Channel Not Tracked",
                message=(
                    f"Twitch channel `{twitch_channel.display_name}` (`{twitch_channel.login}`) "
                    "is not tracked in this Discord channel. Add it first with `/channel add`."
                ),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
        if account is None or not account.access_token:
            return DiscordCommandResult(
                title="No Linked Account",
                message=(
                    "This Discord channel must link a Twitch account first with `/account link` "
                    "before it can send Twitch messages."
                ),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        account = await self._ensure_account_token(account)
        try:
            await self.twitch_api.send_chat_message(
                access_token=account.access_token,
                client_id=account.client_id,
                sender_id=account.twitch_user_id,
                broadcaster_id=twitch_channel.user_id,
                message=message,
                reply_parent_message_id=event.reply_parent_message_id,
            )
        except TwitchAuthenticationError:
            refreshed = await self._try_refresh_account(account)
            if refreshed is None:
                if thread.account_id is not None:
                    self.account_repository.remove_by_account_id(thread.account_id)
                    self.thread_repository.set_account_id(discord_channel_id=thread.discord_channel_id, account_id=None)
                return DiscordCommandResult(
                    title="Twitch Account Expired",
                    message=(
                        "The linked Twitch account for this Discord channel is no longer valid. "
                        "Link it again with `/account link`."
                    ),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            await self.twitch_api.send_chat_message(
                access_token=refreshed.access_token,
                client_id=refreshed.client_id,
                sender_id=refreshed.twitch_user_id,
                broadcaster_id=twitch_channel.user_id,
                message=message,
                reply_parent_message_id=event.reply_parent_message_id,
            )

        if event.reply_parent_message_id:
            return DiscordCommandResult(
                title="Twitch Reply Sent",
                message=(
                    f"Sent a Twitch reply to `{twitch_channel.display_name}` (`{twitch_channel.login}`).\n"
                    f"Reply Target: `{event.reply_parent_message_id}`\n"
                    f"Message: `{message}`"
                ),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )
        return DiscordCommandResult(
            title="Twitch Message Sent",
            message=(
                f"Sent a Twitch message to `{twitch_channel.display_name}` (`{twitch_channel.login}`).\n"
                f"Message: `{message}`"
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
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
        return stored
