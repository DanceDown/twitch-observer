from __future__ import annotations

"""Business logic for manually sending Twitch chat messages from Discord."""

import logging
from dataclasses import dataclass, field

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError, TwitchAuthenticationError
from src.database.connection import ChannelRepository, ThreadRepository, TwitchAccountRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    DiscordWriteRequestedEvent,
    EventType,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.services.twitch_runtime import ensure_fresh_linked_account, refresh_linked_account
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
    token_refresh_skew_seconds: int
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_WRITE_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordWriteRequestedEvent) -> None:
        try:
            result = await self._send_message(event)
        except ValueError as error:
            result = self._event_result(
                event,
                "results.validation_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except TwitchAPIError as error:
            result = self._event_result(
                event,
                "results.twitch_api_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling Twitch write command.")
            result = self._event_result(
                event,
                "results.unexpected_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _send_message(self, event: DiscordWriteRequestedEvent) -> DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if thread is None:
            return self.localizer.result(
                "results.not_joined",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=event.requester_id,
            permission_repository=self.permission_repository,
            required_permission=ObserverPermission.SEND_TWITCH_MESSAGES,
        ):
            return self.localizer.thread_result(
                "results.write.permission_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        message = event.message.strip()
        if not message:
            raise ValueError(self.localizer.text("results.write.empty_message", language=thread.language))
        if len(message) > 500:
            raise ValueError(self.localizer.text("results.write.message_too_long", language=thread.language))

        refresh_lookup = getattr(self.twitch_api, "refresh_user_by_login", self.twitch_api.get_user_by_login)
        twitch_channel = await refresh_lookup(event.twitch_channel_login)
        tracked_channel = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, twitch_channel.user_id)
        if tracked_channel is None:
            return self.localizer.thread_result(
                "results.write.channel_not_tracked",
                thread=thread,
                DISPLAY_NAME=twitch_channel.display_name,
                LOGIN=twitch_channel.login,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
        if account is None or not account.access_token:
            return self.localizer.thread_result(
                "results.write.no_linked_account",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        account = await ensure_fresh_linked_account(
            account=account,
            account_repository=self.account_repository,
            twitch_api=self.twitch_api,
            token_refresh_skew_seconds=self.token_refresh_skew_seconds,
            thread_repository=self.thread_repository,
            thread=thread,
        ) or account
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
            refreshed = await refresh_linked_account(
                account=account,
                account_repository=self.account_repository,
                twitch_api=self.twitch_api,
                thread_repository=self.thread_repository,
                thread=thread,
            )
            if refreshed is None:
                if thread.account_id is not None:
                    self.account_repository.remove_by_account_id(thread.account_id)
                    self.thread_repository.set_account_id(discord_channel_id=thread.discord_channel_id, account_id=None)
                return self.localizer.thread_result(
                    "results.write.account_expired",
                    thread=thread,
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
            return self.localizer.thread_result(
                "results.write.reply_sent",
                thread=thread,
                DISPLAY_NAME=twitch_channel.display_name,
                LOGIN=twitch_channel.login,
                REPLY_TARGET=event.reply_parent_message_id,
                MESSAGE=message,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )
        return self.localizer.thread_result(
            "results.write.message_sent",
            thread=thread,
            DISPLAY_NAME=twitch_channel.display_name,
            LOGIN=twitch_channel.login,
            MESSAGE=message,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    def _event_result(
        self,
        event: DiscordWriteRequestedEvent,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        return self.localizer.thread_result(
            key,
            thread=thread,
            style=style,
            ephemeral=ephemeral,
            **placeholders,
        )
