from __future__ import annotations

"""Business logic for Twitch account linking through the Device Code Flow."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.adapters.twitch_api import (
    TwitchAPIClient,
    TwitchAPIConfigurationError,
    TwitchAPIError,
    TwitchAuthenticationError,
    TwitchDeviceFlowError,
)
from src.database.connection import (
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
    TwitchDeviceFlowRecord,
    TwitchDeviceFlowRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordAccountRequestedEvent,
    DiscordCommandResult,
    DiscordResultStyle,
    EventType,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


def _format_timestamp(raw_value: str | None) -> str:
    """Render ISO timestamps in a shorter human-friendly form."""
    if raw_value is None:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return raw_value
    return parsed.strftime("%d-%m-%Y %H:%M:%S %Z").strip() or parsed.isoformat(sep=" ", timespec="seconds")


class AccountNotificationSender:
    """Interface for optionally notifying Discord users about link results."""

    async def send_account_result(
        self,
        discord_user_id: int,
        discord_channel_id: int | None,
        result: DiscordCommandResult,
    ) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass(slots=True)
class AccountCommandService:
    """Handle `/account` commands using Twitch's Device Code Flow."""

    event_bus: EventBus
    account_repository: TwitchAccountRepository
    device_flow_repository: TwitchDeviceFlowRepository
    thread_repository: ThreadRepository
    twitch_api: TwitchAPIClient
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_ACCOUNT_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordAccountRequestedEvent) -> None:
        try:
            if event.action == "link":
                result = await self._start_link(event)
            elif event.action == "unlink":
                result = await self._unlink_account(event)
            elif event.action == "show":
                result = self._show_account_removed(event)
            else:
                result = self.localizer.result(
                    "results.account.unsupported_action",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
        except (TwitchAuthenticationError, TwitchDeviceFlowError, TwitchAPIConfigurationError, ValueError) as error:
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

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _start_link(self, event: DiscordAccountRequestedEvent) -> DiscordCommandResult:
        thread = self._require_owner_thread(event=event)
        if isinstance(thread, DiscordCommandResult):
            return thread
        if thread.account_id is not None:
            account = self.account_repository.get_by_account_id(thread.account_id)
            account_name = await self._display_name_for_account(account) if account is not None else None
            return self.localizer.thread_result(
                "results.account.already_linked",
                thread=thread,
                DISPLAY_NAME=account_name or self.localizer.text("results.account.existing_account", language=thread.language),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        existing_pending = self.device_flow_repository.get_by_discord_channel_id(thread.discord_channel_id)
        if existing_pending is not None and existing_pending.status == "pending":
            return self.localizer.thread_result(
                "results.account.login_pending",
                thread=thread,
                VERIFICATION_URI=existing_pending.verification_uri,
                USER_CODE=existing_pending.user_code,
                EXPIRES_AT=_format_timestamp(existing_pending.expires_at),
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        start = await self.twitch_api.start_device_code_flow(scopes=("user:write:chat",))
        expires_at = (datetime.now(UTC) + timedelta(seconds=start.expires_in)).isoformat()
        pending = self.device_flow_repository.upsert_pending_flow(
            discord_user_id=event.requester_id,
            discord_channel_id=thread.discord_channel_id,
            device_code=start.device_code,
            user_code=start.user_code,
            verification_uri=start.verification_uri,
            interval_seconds=start.interval,
            expires_at=expires_at,
            scope=("user:write:chat",),
        )
        return self.localizer.thread_result(
            "results.account.finish_login",
            thread=thread,
            VERIFICATION_URI=pending.verification_uri,
            USER_CODE=pending.user_code,
            EXPIRES_AT=_format_timestamp(pending.expires_at),
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    async def _unlink_account(self, event: DiscordAccountRequestedEvent) -> DiscordCommandResult:
        thread = self._require_owner_thread(event=event)
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
            return self.localizer.thread_result(
                "results.account.no_linked_account",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        return self.localizer.thread_result(
            "results.account.unlinked",
            thread=thread,
            DISPLAY_NAME=account_name or self.localizer.text("results.account.existing_account", language=thread.language),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    def _show_account_removed(self, event: DiscordAccountRequestedEvent) -> DiscordCommandResult:
        thread = None if event.discord_channel_id is None else self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        return self.localizer.thread_result(
            "results.account.show_moved",
            thread=thread,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    def _require_thread_with_permission(
        self,
        *,
        event: DiscordAccountRequestedEvent,
        required_permission: ObserverPermission,
        denial_key: str,
    ) -> ThreadRecord | DiscordCommandResult:
        if (
            event.discord_channel_id is None
            or (thread := self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)) is None
        ):
            return self.localizer.result(
                "results.not_joined",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=event.requester_id,
            permission_repository=self.permission_repository,
            required_permission=required_permission,
        ):
            return self.localizer.thread_result(
                denial_key,
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    def _require_owner_thread(self, *, event: DiscordAccountRequestedEvent) -> ThreadRecord | DiscordCommandResult:
        thread = self._require_thread_with_permission(
            event=event,
            required_permission=ObserverPermission.CONTROL_OBSERVER,
            denial_key="results.account.permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread
        if thread.owner_id != event.requester_id:
            return self.localizer.thread_result(
                "results.account.owner_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    async def _display_name_for_account(self, account) -> str | None:
        if account is None:
            return None
        try:
            user = await self.twitch_api.get_user_by_id(account.twitch_user_id)
        except Exception:
            return account.twitch_login
        return user.display_name

    def _event_result(
        self,
        event: DiscordAccountRequestedEvent,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        thread = None if event.discord_channel_id is None else self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        return self.localizer.thread_result(key, thread=thread, style=style, ephemeral=ephemeral, **placeholders)


@dataclass(slots=True)
class DeviceFlowPollingService:
    """Poll pending Twitch Device Code logins until they complete or fail."""

    device_flow_repository: TwitchDeviceFlowRepository
    account_repository: TwitchAccountRepository
    thread_repository: ThreadRepository
    twitch_api: TwitchAPIClient
    poll_interval_seconds: float
    notifier: AccountNotificationSender | None = None
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
            except Exception:
                logger.exception("Unexpected error while polling pending Twitch device logins.")
            await asyncio.sleep(self.poll_interval_seconds)

    async def poll_once(self) -> None:
        """Poll every currently pending device flow that is due."""
        now = datetime.now(UTC)
        for pending in self.device_flow_repository.list_pending_flows():
            try:
                if self._is_expired(pending, now):
                    self.device_flow_repository.mark_failed(
                        discord_channel_id=pending.discord_channel_id or 0,
                        last_error="The Twitch login code expired before it was confirmed.",
                    )
                    await self._notify(
                        pending.discord_user_id,
                        self._result_for_pending(
                            pending,
                            "results.account.login_expired",
                            style=DiscordResultStyle.ERROR,
                            ephemeral=True,
                        ),
                        pending.discord_channel_id,
                    )
                    continue

                if not self._is_due_for_poll(pending, now):
                    continue

                self.device_flow_repository.touch_polled(discord_channel_id=pending.discord_channel_id or 0)
                result = await self.twitch_api.poll_device_code_flow(
                    device_code=pending.device_code,
                    scopes=pending.scope,
                )
                if result.status == "pending":
                    continue
                if result.status == "slow_down":
                    self.device_flow_repository.update_interval(
                        discord_channel_id=pending.discord_channel_id or 0,
                        interval_seconds=pending.interval_seconds + int(result.interval or 0),
                    )
                    continue
                if result.status == "failed":
                    self.device_flow_repository.mark_failed(
                        discord_channel_id=pending.discord_channel_id or 0,
                        last_error=result.error_message or "The Twitch login was denied or expired.",
                    )
                    await self._notify(
                        pending.discord_user_id,
                        self._result_for_pending(
                            pending,
                            "results.account.login_failed",
                            style=DiscordResultStyle.ERROR,
                            ephemeral=True,
                        ),
                        pending.discord_channel_id,
                    )
                    continue
                if result.status != "success" or result.token_bundle is None:
                    continue

                validated = await self.twitch_api.validate_user_access_token(result.token_bundle.access_token)
                if "user:write:chat" not in validated.scopes:
                    self.device_flow_repository.mark_failed(
                        discord_channel_id=pending.discord_channel_id or 0,
                        last_error="The linked Twitch token is missing `user:write:chat`.",
                    )
                    await self._notify(
                        pending.discord_user_id,
                        self._result_for_pending(
                            pending,
                            "results.account.login_missing_scope",
                            style=DiscordResultStyle.ERROR,
                            ephemeral=True,
                        ),
                        pending.discord_channel_id,
                    )
                    continue

                expires_at = (now + timedelta(seconds=result.token_bundle.expires_in)).isoformat()
                thread = (
                    self.thread_repository.get_by_discord_channel_id(pending.discord_channel_id)
                    if pending.discord_channel_id is not None
                    else None
                )
                if thread is None:
                    self.device_flow_repository.mark_failed(
                        discord_channel_id=pending.discord_channel_id or 0,
                        last_error="The Discord channel is no longer joined.",
                    )
                    continue

                if thread.account_id is not None:
                    self.account_repository.remove_by_account_id(thread.account_id)

                stored = self.account_repository.create_account(
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
                self.thread_repository.set_account_id(
                    discord_channel_id=thread.discord_channel_id,
                    account_id=stored.account_id,
                )
                self.device_flow_repository.remove_by_discord_channel_id(thread.discord_channel_id)
                await self._notify(
                    pending.discord_user_id,
                    self._result_for_thread(
                        thread,
                        "results.account.linked",
                        DISPLAY_NAME=await self._display_name_for_user_id(stored.twitch_user_id, stored.twitch_login),
                        style=DiscordResultStyle.SUCCESS,
                        ephemeral=True,
                    ),
                    pending.discord_channel_id,
                )
            except Exception:
                logger.exception("Unexpected error while processing device flow for discord_user_id=%s", pending.discord_user_id)

    def invalidate_account(self, discord_user_id: int) -> None:
        """Remove a broken linked account but keep configured auto-replies intact."""
        account = self.account_repository.get_by_discord_user_id(discord_user_id)
        if account is not None:
            self.account_repository.remove_by_account_id(account.account_id)

    async def _notify(self, discord_user_id: int, result: DiscordCommandResult, discord_channel_id: int | None) -> None:
        if self.notifier is None:
            return
        await self.notifier.send_account_result(discord_user_id, discord_channel_id, result)

    def _result_for_pending(
        self,
        pending: TwitchDeviceFlowRecord,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        thread = (
            None if pending.discord_channel_id is None else self.thread_repository.get_by_discord_channel_id(pending.discord_channel_id)
        )
        return self.localizer.thread_result(key, thread=thread, style=style, ephemeral=ephemeral, **placeholders)

    def _result_for_thread(
        self,
        thread: ThreadRecord,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        return self.localizer.thread_result(key, thread=thread, style=style, ephemeral=ephemeral, **placeholders)

    async def _display_name_for_user_id(self, twitch_user_id: str, fallback: str) -> str:
        try:
            user = await self.twitch_api.get_user_by_id(twitch_user_id)
        except Exception:
            return fallback
        return user.display_name

    @staticmethod
    def _is_expired(pending: TwitchDeviceFlowRecord, now: datetime) -> bool:
        return now >= datetime.fromisoformat(pending.expires_at)

    @staticmethod
    def _is_due_for_poll(pending: TwitchDeviceFlowRecord, now: datetime) -> bool:
        if pending.last_polled_at is None:
            return True
        last_polled = datetime.fromisoformat(pending.last_polled_at)
        return now >= last_polled + timedelta(seconds=pending.interval_seconds)
