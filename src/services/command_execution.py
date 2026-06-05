"""Shared command execution helpers for Discord-triggered service handlers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from src.gateways.twitch_api import (
    TwitchAPIConfigurationError,
    TwitchAPIError,
    TwitchAuthenticationError,
    TwitchChannelNotFoundError,
    TwitchDeviceFlowError,
)
from src.database.connection import ThreadRecord, ThreadRepository, TwitchAccountRecord, TwitchAccountRepository, UserPermissionRepository
from src.discord_results import build_result, build_thread_result
from src.errors import DatabasePoolExhaustedError
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)

CommandT = TypeVar("CommandT")


class ThreadScopedCommand(Protocol):
    """Minimal shape for commands bound to one Discord context."""

    discord_channel_id: int
    requester_id: int


@dataclass(slots=True)
class ThreadCommandGuards:
    """Reusable guard helpers for thread-scoped command handlers."""

    thread_repository: ThreadRepository
    permission_repository: UserPermissionRepository | None
    account_repository: TwitchAccountRepository | None
    localizer: Localizer
    not_joined_key: str

    async def require_thread(self, command: ThreadScopedCommand) -> ThreadRecord | DiscordCommandResult:
        thread = await self.thread_repository.get_by_discord_channel_id(command.discord_channel_id)
        if thread is None:
            return build_result(
                self.localizer,
                self.not_joined_key,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    async def require_permission(
        self,
        command: ThreadScopedCommand,
        *,
        permission: ObserverPermission,
        denial_key: str,
    ) -> ThreadRecord | DiscordCommandResult:
        thread = await self.require_thread(command)
        if isinstance(thread, DiscordCommandResult):
            return thread
        if not await thread_has_permission(
            thread=thread,
            requester_id=command.requester_id,
            permission_repository=self.permission_repository,
            required_permission=permission,
        ):
            return build_thread_result(
                self.localizer,
                denial_key,
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    async def require_owner(
        self,
        command: ThreadScopedCommand,
        *,
        denial_key: str,
    ) -> ThreadRecord | DiscordCommandResult:
        thread = await self.require_thread(command)
        if isinstance(thread, DiscordCommandResult):
            return thread
        if thread.owner_id != command.requester_id:
            return build_thread_result(
                self.localizer,
                denial_key,
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    async def require_linked_account(
        self,
        thread: ThreadRecord,
        *,
        denial_key: str,
    ) -> TwitchAccountRecord | DiscordCommandResult:
        if self.account_repository is None or thread.account_id is None:
            return build_thread_result(
                self.localizer,
                denial_key,
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        account = await self.account_repository.get_by_account_id(thread.account_id)
        if account is None or not account.access_token:
            return build_thread_result(
                self.localizer,
                denial_key,
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return account

    async def require_tracked_channels(
        self,
        thread: ThreadRecord,
        *,
        channel_count_lookup: Callable[[int], Awaitable[int]],
        denial_key: str,
    ) -> DiscordCommandResult | None:
        if await channel_count_lookup(thread.thread_id) > 0:
            return None
        return build_thread_result(
            self.localizer,
            denial_key,
            thread=thread,
            style=DiscordResultStyle.ERROR,
            ephemeral=True,
        )


class CommandExecutionRunner:
    """Shared error normalization for direct command handlers."""

    def __init__(
        self,
        *,
        localizer: Localizer,
        resolve_thread: Callable[[object], Awaitable[ThreadRecord | None]],
        validation_error_key: str,
        twitch_api_error_key: str,
        unexpected_error_key: str,
    ) -> None:
        self._localizer = localizer
        self._resolve_thread = resolve_thread
        self._validation_error_key = validation_error_key
        self._twitch_api_error_key = twitch_api_error_key
        self._unexpected_error_key = unexpected_error_key

    async def run(
        self,
        command: CommandT,
        operation: Callable[[], Awaitable[DiscordCommandResult]],
        *,
        logger_: logging.Logger,
        validation_exceptions: tuple[type[Exception], ...] = (
            ValueError,
            TwitchAuthenticationError,
            TwitchDeviceFlowError,
            TwitchAPIConfigurationError,
            TwitchChannelNotFoundError,
        ),
    ) -> DiscordCommandResult:
        try:
            result = await operation()
        except validation_exceptions as error:
            result = await self._thread_result(
                command,
                self._validation_error_key,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
            )
        except TwitchAPIError as error:
            result = await self._thread_result(
                command,
                self._twitch_api_error_key,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
            )
        except DatabasePoolExhaustedError as error:
            logger_.error("Database pool exhausted while handling %s.", command.__class__.__name__)
            result = await self._thread_result(
                command,
                self._unexpected_error_key,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
            )
        except Exception as error:
            logger_.exception("Unexpected error while handling %s.", command.__class__.__name__)
            result = await self._thread_result(
                command,
                self._unexpected_error_key,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                DETAIL=str(error),
            )
        return result

    async def _thread_result(
        self,
        command: object,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        thread = await self._resolve_thread(command)
        return build_thread_result(
            self._localizer,
            key,
            thread=thread,
            style=style,
            ephemeral=ephemeral,
            **placeholders,
        )
