"""Business logic for Twitch account linking through the Device Code Flow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.gateways.twitch_api import TwitchAPIError
from src.database.connection import (
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
    TwitchDeviceFlowRepository,
    UserPermissionRepository,
)
from src.discord_results import build_result, build_thread_result, discord_user_mention
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    StartAccountLinkCommand,
    UnlinkAccountCommand,
)
from src.localization import Localizer
from src.services.account_support import AccountNotificationSender, format_account_timestamp
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.services.twitch_gateways import TwitchAccountGateway
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)
__all__ = ("AccountCommandService", "AccountNotificationSender")

AccountCommand = StartAccountLinkCommand | UnlinkAccountCommand

@dataclass(slots=True)
class AccountCommandService:
    """Handle `/account` commands using Twitch's Device Code Flow."""

    account_repository: TwitchAccountRepository
    device_flow_repository: TwitchDeviceFlowRepository
    thread_repository: ThreadRepository
    twitch_api: TwitchAccountGateway
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    _runner: CommandExecutionRunner = field(init=False, repr=False)
    _guards: ThreadCommandGuards = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._runner = CommandExecutionRunner(localizer=self.localizer, resolve_thread=self._resolve_thread)
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=self.account_repository,
            localizer=self.localizer,
        )

    async def handle_link_command(self, command: StartAccountLinkCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._start_link(command), logger_=logger)

    async def handle_unlink_command(self, command: UnlinkAccountCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._unlink_account(command), logger_=logger)

    async def _start_link(self, command: StartAccountLinkCommand) -> DiscordCommandResult:
        thread = self._require_owner_thread(command=command)
        if isinstance(thread, DiscordCommandResult):
            return thread
        if thread.account_id is not None:
            account = self.account_repository.get_by_account_id(thread.account_id)
            account_name = await self._display_name_for_account(account) if account is not None else None
            return build_thread_result(
                self.localizer,
                "results.account.already_linked",
                thread=thread,
                DISPLAY_NAME=account_name or self.localizer.text("results.account.existing_account", language=thread.language),
                LOGIN=account.twitch_login if account is not None else "",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        existing_pending = self.device_flow_repository.get_by_discord_channel_id(thread.discord_channel_id)
        if existing_pending is not None and existing_pending.status == "pending":
            return build_thread_result(
                self.localizer,
                "results.account.login_pending",
                thread=thread,
                VERIFICATION_URI=existing_pending.verification_uri,
                USER_CODE=existing_pending.user_code,
                EXPIRES_AT=format_account_timestamp(existing_pending.expires_at),
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        start = await self.twitch_api.start_device_code_flow(scopes=("user:write:chat",))
        expires_at = (datetime.now().astimezone() + timedelta(seconds=start.expires_in)).isoformat()
        pending = self.device_flow_repository.upsert_pending_flow(
            discord_user_id=command.requester_id,
            discord_channel_id=thread.discord_channel_id,
            device_code=start.device_code,
            user_code=start.user_code,
            verification_uri=start.verification_uri,
            interval_seconds=start.interval,
            expires_at=expires_at,
            scope=("user:write:chat",),
        )
        return build_thread_result(
            self.localizer,
            "results.account.finish_login",
            thread=thread,
            VERIFICATION_URI=pending.verification_uri,
            USER_CODE=pending.user_code,
            EXPIRES_AT=format_account_timestamp(pending.expires_at),
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    async def _unlink_account(self, command: UnlinkAccountCommand) -> DiscordCommandResult:
        thread = self._require_owner_thread(command=command)
        if isinstance(thread, DiscordCommandResult):
            return thread

        removed_account = False
        account_name = None
        if thread.account_id is not None:
            account = self.account_repository.get_by_account_id(thread.account_id)
            account_name = await self._display_name_for_account(account) if account is not None else None
            removed_account = self.account_repository.remove_by_account_id(thread.account_id)
            self.thread_repository.set_account_id(discord_channel_id=thread.discord_channel_id, account_id=None)
        removed_pending = self.device_flow_repository.remove_by_discord_channel_id(thread.discord_channel_id)
        if not removed_account and not removed_pending:
            return build_thread_result(
                self.localizer,
                "results.account.no_linked_account",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        return build_thread_result(
            self.localizer,
            "results.account.unlinked",
            thread=thread,
            DISPLAY_NAME=account_name or self.localizer.text("results.account.existing_account", language=thread.language),
            LOGIN=account.twitch_login if account is not None else "",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    def _require_thread_with_permission(
        self,
        *,
        command: AccountCommand,
        required_permission: ObserverPermission,
        denial_key: str,
    ) -> ThreadRecord | DiscordCommandResult:
        if command.discord_channel_id is None:
            return build_result(
                self.localizer,
                "results.not_joined",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return self._guards.require_permission(
            _AccountScopedCommand(
                discord_channel_id=command.discord_channel_id,
                requester_id=command.requester_id,
            ),
            permission=required_permission,
            denial_key=denial_key,
        )

    def _require_owner_thread(self, *, command: AccountCommand) -> ThreadRecord | DiscordCommandResult:
        thread = self._require_thread_with_permission(
            command=command,
            required_permission=ObserverPermission.CONTROL_OBSERVER,
            denial_key="results.account.permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread
        if thread.owner_id != command.requester_id:
            return build_thread_result(
                self.localizer,
                "results.account.owner_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    async def _display_name_for_account(self, account: TwitchAccountRecord | None) -> str | None:
        if account is None:
            return None
        try:
            user = await self.twitch_api.get_user_by_id(account.twitch_user_id)
        except TwitchAPIError:
            return account.twitch_login
        return user.display_name

    def _resolve_thread(self, command: AccountCommand) -> ThreadRecord | None:
        if command.discord_channel_id is None:
            return None
        return self.thread_repository.get_by_discord_channel_id(command.discord_channel_id)


@dataclass(slots=True, frozen=True)
class _AccountScopedCommand:
    discord_channel_id: int
    requester_id: int
