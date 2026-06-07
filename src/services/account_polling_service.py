"""Background polling for pending Twitch device-code account links."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import psycopg

from src.errors import DatabasePoolExhaustedError
from src.gateways.twitch_api import TwitchAPIError
from src.database.connection import (
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
    TwitchDeviceFlowRecord,
    TwitchDeviceFlowRepository,
)
from src.discord_results import build_thread_result
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.services.account_support import AccountNotificationSender
from src.services.twitch_gateways import TwitchAccountGateway

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DeviceFlowPollProcessor:
    """Process one pending Twitch device-code login attempt."""

    device_flow_repository: TwitchDeviceFlowRepository
    account_repository: TwitchAccountRepository
    thread_repository: ThreadRepository
    twitch_api: TwitchAccountGateway
    localizer: Localizer

    async def process_pending(
        self,
        pending: TwitchDeviceFlowRecord,
        *,
        now: datetime,
        notify: Callable[[int, DiscordCommandResult, int | None], Awaitable[None]],
    ) -> None:
        """Process one pending flow if it is due and still valid."""
        if self._is_expired(pending, now):
            await self.device_flow_repository.mark_failed(
                    discord_channel_id=pending.discord_channel_id or 0,
                    last_error="The Twitch login code expired before it was confirmed.",
                )
            
            await notify(
                pending.discord_user_id,
                await self._result_for_pending(
                    pending,
                    "results.account.login_expired",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
                pending.discord_channel_id,
            )
            return

        if not self._is_due_for_poll(pending, now):
            return

        await self.device_flow_repository.touch_polled(discord_channel_id=pending.discord_channel_id or 0)
        result = await self.twitch_api.poll_device_code_flow(
            device_code=pending.device_code,
            scopes=pending.scope,
        )
        if result.status == "pending":
            return
        if result.status == "slow_down":
            await self.device_flow_repository.update_interval(
                    discord_channel_id=pending.discord_channel_id or 0,
                    interval_seconds=pending.interval_seconds + int(result.interval or 0),
                )
            
            return
        if result.status == "failed":
            await self.device_flow_repository.mark_failed(
                    discord_channel_id=pending.discord_channel_id or 0,
                    last_error=result.error_message or "The Twitch login was denied or expired.",
                )
            
            await notify(
                pending.discord_user_id,
                await self._result_for_pending(
                    pending,
                    "results.account.login_failed",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
                pending.discord_channel_id,
            )
            return
        if result.status != "success" or result.token_bundle is None:
            return

        validated = await self.twitch_api.validate_user_access_token(result.token_bundle.access_token)
        if "user:write:chat" not in validated.scopes:
            await self.device_flow_repository.mark_failed(
                    discord_channel_id=pending.discord_channel_id or 0,
                    last_error="The linked Twitch token is missing `user:write:chat`.",
                )
            
            await notify(
                pending.discord_user_id,
                await self._result_for_pending(
                    pending,
                    "results.account.login_missing_scope",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
                pending.discord_channel_id,
            )
            return

        expires_at = (now + timedelta(seconds=result.token_bundle.expires_in)).isoformat()
        thread = (
            await self.thread_repository.get_by_discord_channel_id(pending.discord_channel_id)
            if pending.discord_channel_id is not None
            else None
        )
        if thread is None:
            await self.device_flow_repository.mark_failed(
                    discord_channel_id=pending.discord_channel_id or 0,
                    last_error="The Discord channel is no longer joined.",
                )
            
            return

        if thread.account_id is not None:
            await self.account_repository.remove_by_account_id(thread.account_id)

        stored = await self.account_repository.create_account(
                discord_user_id=pending.discord_user_id,
                twitch_user_id=validated.user_id,
                twitch_login=validated.login,
                client_id=validated.client_id,
                access_token=result.token_bundle.access_token,
                refresh_token=result.token_bundle.refresh_token,
                expires_at=expires_at,
                scope=result.token_bundle.scope,
                token_type=result.token_bundle.token_type,
            )
        
        await self.thread_repository.set_account_id(
                discord_channel_id=thread.discord_channel_id,
                account_id=stored.account_id,
            )
        
        await self.device_flow_repository.remove_by_discord_channel_id(thread.discord_channel_id)
        await notify(
            pending.discord_user_id,
            self._result_for_thread(
                thread,
                "results.account.linked",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=True,
                sources={
                    "view": {
                        "account": {
                            "display_name": await self._display_name_for_user_id(stored.twitch_user_id, stored.twitch_login),
                            "login": stored.twitch_login,
                        },
                        "requester_id": pending.discord_user_id,
                    }
                },
            ),
            pending.discord_channel_id,
        )

    async def _display_name_for_user_id(self, twitch_user_id: str, fallback: str) -> str:
        try:
            user = await self.twitch_api.get_user_by_id(twitch_user_id)
        except TwitchAPIError:
            return fallback
        return user.display_name

    async def _result_for_pending(
        self,
        pending: TwitchDeviceFlowRecord,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        sources: dict[str, object] | None = None,
    ) -> DiscordCommandResult:
        thread = (
            None
            if pending.discord_channel_id is None
            else await self.thread_repository.get_by_discord_channel_id(pending.discord_channel_id)
        )
        return build_thread_result(
            self.localizer,
            key,
            thread=thread,
            style=style,
            ephemeral=ephemeral,
            sources=sources,
        )

    def _result_for_thread(
        self,
        thread: ThreadRecord,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        sources: dict[str, object] | None = None,
    ) -> DiscordCommandResult:
        return build_thread_result(
            self.localizer,
            key,
            thread=thread,
            style=style,
            ephemeral=ephemeral,
            sources=sources,
        )

    @staticmethod
    def _is_expired(pending: TwitchDeviceFlowRecord, now: datetime) -> bool:
        return now >= datetime.fromisoformat(pending.expires_at)

    @staticmethod
    def _is_due_for_poll(pending: TwitchDeviceFlowRecord, now: datetime) -> bool:
        if pending.last_polled_at is None:
            return True
        last_polled = datetime.fromisoformat(pending.last_polled_at)
        return now >= last_polled + timedelta(seconds=pending.interval_seconds)


@dataclass(slots=True)
class DeviceFlowPollingService:
    """Poll pending Twitch Device Code logins until they complete or fail."""

    device_flow_repository: TwitchDeviceFlowRepository
    account_repository: TwitchAccountRepository
    thread_repository: ThreadRepository
    twitch_api: TwitchAccountGateway
    poll_interval_seconds: float
    notifier: AccountNotificationSender
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    async def start(self) -> None:
        """Start the background polling loop once."""
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="twitch-device-flow-poller")

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.poll_once()
            except DatabasePoolExhaustedError:
                logger.error("Pending Twitch device login polling skipped because the database pool is exhausted.")
            except psycopg.Error:
                logger.exception("Pending Twitch device login polling failed because PostgreSQL returned an error.")
            except TwitchAPIError:
                logger.exception("Pending Twitch device login polling failed because Twitch returned an API error.")
            await asyncio.sleep(self.poll_interval_seconds)

    async def poll_once(self) -> None:
        """Poll every currently pending device flow that is due."""
        processor = DeviceFlowPollProcessor(
            device_flow_repository=self.device_flow_repository,
            account_repository=self.account_repository,
            thread_repository=self.thread_repository,
            twitch_api=self.twitch_api,
            localizer=self.localizer,
        )
        now = datetime.now(UTC)
        for pending in await self.device_flow_repository.list_pending_flows():
            try:
                await processor.process_pending(
                    pending,
                    now=now,
                    notify=self._notify,
                )
            except DatabasePoolExhaustedError:
                logger.error(
                    "Device flow processing skipped because the database pool is exhausted for discord_user_id=%s",
                    pending.discord_user_id,
                )
            except psycopg.Error:
                logger.exception(
                    "Device flow processing failed because PostgreSQL returned an error for discord_user_id=%s",
                    pending.discord_user_id,
                )
            except TwitchAPIError:
                logger.exception(
                    "Device flow processing failed because Twitch returned an API error for discord_user_id=%s",
                    pending.discord_user_id,
                )
            except ValueError:
                logger.exception(
                    "Device flow processing failed because stored timestamps are invalid for discord_user_id=%s",
                    pending.discord_user_id,
                )

    async def invalidate_account(self, discord_user_id: int) -> None:
        """Remove a broken linked account but keep configured auto-replies intact."""
        account = await self.account_repository.get_by_discord_user_id(discord_user_id)
        if account is not None:
            await self.account_repository.remove_by_account_id(account.account_id)

    async def _notify(self, discord_user_id: int, result: DiscordCommandResult, discord_channel_id: int | None) -> None:
        await self.notifier.send_account_result(discord_user_id, discord_channel_id, result)
