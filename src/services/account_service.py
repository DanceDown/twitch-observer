from __future__ import annotations

"""Business logic for Twitch account linking through the Device Code Flow."""

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging

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
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


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

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_ACCOUNT_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordAccountRequestedEvent) -> None:
        try:
            if event.action == "link":
                result = await self._start_link(event)
            elif event.action == "unlink":
                result = self._unlink_account(event)
            elif event.action == "show":
                result = self._show_account(event)
            else:
                result = DiscordCommandResult(
                    title="Validation Error",
                    message="Unsupported account action.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
        except (TwitchAuthenticationError, TwitchDeviceFlowError, TwitchAPIConfigurationError, ValueError) as error:
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

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _start_link(self, event: DiscordAccountRequestedEvent) -> DiscordCommandResult:
        thread = self._require_owner_thread(event=event)
        if isinstance(thread, DiscordCommandResult):
            return thread
        start = await self.twitch_api.start_device_code_flow(scopes=("user:write:chat",))
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=start.expires_in)).isoformat()
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
        return DiscordCommandResult(
            title="Finish Twitch Login",
            message=(
                "Open the activation link below, sign in to Twitch, and confirm the login.\n"
                f"Verification URL: `{pending.verification_uri}`\n"
                f"User Code: `{pending.user_code}`\n"
                f"Expires At: `{pending.expires_at}`\n"
                "This login is bound only to the current Discord thread/channel. "
                "You can use `/account show` to check the current status."
            ),
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    def _unlink_account(self, event: DiscordAccountRequestedEvent) -> DiscordCommandResult:
        thread = self._require_owner_thread(event=event)
        if isinstance(thread, DiscordCommandResult):
            return thread

        removed_account = False
        if thread.account_id is not None:
            removed_account = self.account_repository.remove_by_account_id(thread.account_id)
            self.thread_repository.set_account_id(discord_channel_id=thread.discord_channel_id, account_id=None)
        removed_pending = self.device_flow_repository.remove_by_discord_channel_id(thread.discord_channel_id)
        if not removed_account and not removed_pending:
            return DiscordCommandResult(
                title="No Linked Account",
                message="There is no linked or pending Twitch account for this Discord channel.",
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        return DiscordCommandResult(
                title="Account Unlinked",
                message=(
                    "Removed the linked Twitch account and any pending login flow for this Discord channel. "
                    "Existing auto-replies were kept and will work again after you link an account later."
                ),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=True,
            )

    def _show_account(self, event: DiscordAccountRequestedEvent) -> DiscordCommandResult:
        thread = self._require_thread_with_permission(
            event=event,
            required_permission=ObserverPermission.VIEW,
            denial_message="You do not have permission to view the linked Twitch account for this Discord channel.",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
        pending = self.device_flow_repository.get_by_discord_channel_id(thread.discord_channel_id)

        sections: list[str] = []
        if account is not None:
            sections.append(
                "Linked Account:\n"
                f"- login: `{account.twitch_login}`\n"
                f"- linked_by_discord_user: `{account.discord_user_id}`\n"
                f"- scopes: `{', '.join(account.scope) or 'none'}`\n"
                f"- expires_at: `{account.expires_at or 'unknown'}`"
            )

        if pending is not None:
            if pending.status == "pending":
                sections.append(
                    "Pending Device Login:\n"
                    f"- verification_url: `{pending.verification_uri}`\n"
                    f"- user_code: `{pending.user_code}`\n"
                    f"- expires_at: `{pending.expires_at}`"
                )
            else:
                sections.append(
                    "Failed Device Login:\n"
                    f"- last_error: `{pending.last_error or 'unknown'}`\n"
                    "Run `/account link` again to start a new login."
                )

        if not sections:
            return DiscordCommandResult(
                title="No Linked Account",
                message="No Twitch account is currently linked, and no login is pending.",
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        return DiscordCommandResult(
            title="Twitch Account Status",
            message="\n\n".join(sections),
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    def _require_thread_with_permission(
        self,
        *,
        event: DiscordAccountRequestedEvent,
        required_permission: ObserverPermission,
        denial_message: str,
    ) -> ThreadRecord | DiscordCommandResult:
        if event.discord_channel_id is None:
            return DiscordCommandResult(
                title="Not Joined",
                message="This command must be used inside a joined Discord thread or channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
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
            required_permission=required_permission,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message=denial_message,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    def _require_owner_thread(self, *, event: DiscordAccountRequestedEvent) -> ThreadRecord | DiscordCommandResult:
        thread = self._require_thread_with_permission(
            event=event,
            required_permission=ObserverPermission.CONTROL_OBSERVER,
            denial_message="You do not have permission to change the Twitch account for this Discord channel.",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread
        if thread.owner_id != event.requester_id:
            return DiscordCommandResult(
                title="Permission Denied",
                message="Only the thread owner may link or unlink the Twitch account used by this Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread


@dataclass(slots=True)
class DeviceFlowPollingService:
    """Poll pending Twitch Device Code logins until they complete or fail."""

    device_flow_repository: TwitchDeviceFlowRepository
    account_repository: TwitchAccountRepository
    thread_repository: ThreadRepository
    twitch_api: TwitchAPIClient
    notifier: AccountNotificationSender | None = None
    poll_interval_seconds: float = 2.0
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
        now = datetime.now(timezone.utc)
        for pending in self.device_flow_repository.list_pending_flows():
            try:
                if self._is_expired(pending, now):
                    self.device_flow_repository.mark_failed(
                        discord_channel_id=pending.discord_channel_id or 0,
                        last_error="The Twitch login code expired before it was confirmed.",
                    )
                    await self._notify(
                        pending.discord_user_id,
                        DiscordCommandResult(
                            title="Twitch Login Expired",
                            message="The pending Twitch device login expired. Run `/account link` again.",
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
                        interval_seconds=pending.interval_seconds + int(result.interval or 5),
                    )
                    continue
                if result.status == "failed":
                    self.device_flow_repository.mark_failed(
                        discord_channel_id=pending.discord_channel_id or 0,
                        last_error=result.error_message or "The Twitch login was denied or expired.",
                    )
                    await self._notify(
                        pending.discord_user_id,
                        DiscordCommandResult(
                            title="Twitch Login Failed",
                            message=(
                                "The Twitch device login did not complete successfully. "
                                "Run `/account link` again to retry."
                            ),
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
                        DiscordCommandResult(
                            title="Twitch Login Failed",
                            message="The authorized token did not include the required `user:write:chat` scope.",
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
                    DiscordCommandResult(
                        title="Twitch Account Linked",
                        message=(
                            f"Linked Twitch account `{stored.twitch_login}`. "
                            "Auto-replies can now send messages as this account."
                        ),
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

    @staticmethod
    def _is_expired(pending: TwitchDeviceFlowRecord, now: datetime) -> bool:
        return now >= datetime.fromisoformat(pending.expires_at)

    @staticmethod
    def _is_due_for_poll(pending: TwitchDeviceFlowRecord, now: datetime) -> bool:
        if pending.last_polled_at is None:
            return True
        last_polled = datetime.fromisoformat(pending.last_polled_at)
        return now >= last_polled + timedelta(seconds=pending.interval_seconds)
