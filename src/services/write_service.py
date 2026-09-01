"""Business logic for manually sending Twitch chat messages from Discord."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from src.database.connection import (
    ChannelRepository,
    ThreadRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
    UserPermissionRepository,
)
from src.discord_results import build_thread_result
from src.events.commands import SendTwitchMessageCommand
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.twitch_events import TwitchChatSendRequest
from src.gateways.twitch_api import TwitchAuthenticationError
from src.localization import Localizer
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.twitch_gateways import TwitchAuthGateway, TwitchChannelLookup, TwitchChatGateway
from src.services.twitch_runtime import LinkedTwitchAccountRefreshContext, ensure_fresh_linked_account, refresh_linked_account
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)

TWITCH_CHAT_MESSAGE_MAX_LENGTH = 500


class TwitchWriteGateway(TwitchChannelLookup, TwitchChatGateway, TwitchAuthGateway, Protocol):
    """Combined protocol for manual Twitch writes."""


@dataclass(slots=True)
class TwitchWriteCommandService:
    """Handle `/write` requests for manual Twitch chat output."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    account_repository: TwitchAccountRepository
    twitch_api: TwitchWriteGateway
    token_refresh_skew_seconds: int
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    _guards: ThreadCommandGuards = field(init=False, repr=False)
    _runner: CommandExecutionRunner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build shared command guards and error handling after injection."""
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=self.account_repository,
            localizer=self.localizer,
            not_joined_key="results.write.not_joined",
        )
        self._runner = CommandExecutionRunner(
            localizer=self.localizer,
            resolve_thread=lambda command: self.thread_repository.get_by_discord_channel_id(command.discord_channel_id),
            validation_error_key="results.write.validation_error",
            twitch_api_error_key="results.write.twitch_api_error",
            unexpected_error_key="results.write.unexpected_error",
        )

    async def handle_request(self, command: SendTwitchMessageCommand) -> DiscordCommandResult:
        """Validate and send one manual Twitch chat message request."""
        return await self._runner.run(command, lambda: self._send_message(command), logger_=logger)

    async def _send_message(self, command: SendTwitchMessageCommand) -> DiscordCommandResult:
        thread = await self._guards.require_permission(
            command,
            permission=ObserverPermission.SEND_TWITCH_MESSAGES,
            denial_key="results.write.permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        message = command.message.strip()
        if not message:
            raise ValueError(self.localizer.text("results.write.empty_message", language=thread.language))
        if len(message) > TWITCH_CHAT_MESSAGE_MAX_LENGTH:
            raise ValueError(self.localizer.text("results.write.message_too_long", language=thread.language))
        twitch_channel = await self.twitch_api.refresh_channel_by_login(command.twitch_channel_login)
        tracked_channel = await self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, twitch_channel.user_id)

        if tracked_channel is None:
            return build_thread_result(
                self.localizer,
                "results.write.channel_not_tracked",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                sources={"view": self._channel_view(twitch_channel.display_name, twitch_channel.login)},
            )

        account = await self._guards.require_linked_account(thread, denial_key="results.write.no_linked_account")
        if isinstance(account, DiscordCommandResult):
            return account

        refresh_context = LinkedTwitchAccountRefreshContext(
            account_repository=self.account_repository,
            twitch_auth=self.twitch_api,
            thread_repository=self.thread_repository,
            thread=thread,
        )
        account = (
            await ensure_fresh_linked_account(
                account=account,
                context=refresh_context,
                token_refresh_skew_seconds=self.token_refresh_skew_seconds,
            )
            or account
        )
        try:
            await self.twitch_api.send_chat_message(
                self._build_send_request(
                    account=account,
                    broadcaster_id=twitch_channel.user_id,
                    message=message,
                    reply_parent_message_id=command.reply_parent_message_id,
                )
            )
        except TwitchAuthenticationError:
            refreshed = await refresh_linked_account(
                account=account,
                context=refresh_context,
            )
            if refreshed is None:
                if thread.account_id is not None:
                    await self.account_repository.remove_by_account_id(thread.account_id)
                    await self.thread_repository.set_account_id(discord_channel_id=thread.discord_channel_id, account_id=None)

                return build_thread_result(
                    self.localizer,
                    "results.write.account_expired",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            await self.twitch_api.send_chat_message(
                self._build_send_request(
                    account=refreshed,
                    broadcaster_id=twitch_channel.user_id,
                    message=message,
                    reply_parent_message_id=command.reply_parent_message_id,
                )
            )

        if command.reply_parent_message_id:
            return build_thread_result(
                self.localizer,
                "results.write.reply_sent",
                thread=thread,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
                sources={
                    "view": {
                        **self._channel_view(twitch_channel.display_name, twitch_channel.login),
                        "reply_target": command.reply_parent_message_id,
                        "message": message,
                        "requester_id": command.requester_id,
                    }
                },
            )
        return build_thread_result(
            self.localizer,
            "results.write.message_sent",
            thread=thread,
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            sources={
                "view": {
                    **self._channel_view(twitch_channel.display_name, twitch_channel.login),
                    "message": message,
                    "requester_id": command.requester_id,
                }
            },
        )

    @staticmethod
    def _channel_view(display_name: str, login: str) -> dict[str, object]:
        return {"channel": {"display_name": display_name, "login": login}}

    @staticmethod
    def _build_send_request(
        *,
        account: TwitchAccountRecord,
        broadcaster_id: str,
        message: str,
        reply_parent_message_id: str | None,
    ) -> TwitchChatSendRequest:
        return TwitchChatSendRequest(
            access_token=account.access_token,
            client_id=account.client_id,
            sender_id=account.twitch_user_id,
            broadcaster_id=broadcaster_id,
            message=message,
            reply_parent_message_id=reply_parent_message_id,
        )
