from __future__ import annotations

"""Business logic for per-thread Discord permission management."""

from dataclasses import dataclass
import logging

from src.database.connection import ThreadRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordPermissionRequestedEvent,
    DiscordResultStyle,
    EventType,
)
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission, permission_from_value

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PermissionCommandService:
    """Handle `/permission` grant/revoke/clear requests."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    permission_repository: UserPermissionRepository

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_PERMISSION_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordPermissionRequestedEvent) -> None:
        try:
            result = self._handle_action(event)
        except ValueError as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling permission command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    def _handle_action(self, event: DiscordPermissionRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.MANAGE_PERMISSIONS,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message="You do not have permission to change permissions in this Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if event.target_user_id == thread.owner_id:
            return DiscordCommandResult(
                title="Validation Error",
                message="The thread owner already has all permissions and cannot be changed here.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if event.action == "clear":
            removed = self.permission_repository.remove_by_user_and_thread(
                discord_user_id=event.target_user_id,
                thread_id=thread.thread_id,
            )
            return DiscordCommandResult(
                title="Permissions Cleared" if removed else "No Permissions Found",
                message=(
                    f"Removed all extra permissions for Discord user `{event.target_user_id}`."
                    if removed
                    else f"Discord user `{event.target_user_id}` has no extra permissions in this channel."
                ),
                style=DiscordResultStyle.SUCCESS if removed else DiscordResultStyle.INFO,
                ephemeral=False if removed else True,
            )

        if event.permission is None:
            raise ValueError("Please choose one permission.")
        permission = permission_from_value(event.permission)
        current = self.permission_repository.get_by_user_and_thread(
            discord_user_id=event.target_user_id,
            thread_id=thread.thread_id,
        )
        current_mask = 0 if current is None else current.permissions

        if event.action == "grant":
            new_mask = current_mask | int(permission)
            updated = self.permission_repository.upsert_permissions(
                discord_user_id=event.target_user_id,
                thread_id=thread.thread_id,
                permissions=new_mask,
            )
            return DiscordCommandResult(
                title="Permission Granted",
                message=f"Granted `{event.permission}` to Discord user `{updated.discord_user_id}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "revoke":
            if not current_mask & int(permission):
                return DiscordCommandResult(
                    title="Permission Not Granted",
                    message=f"Discord user `{event.target_user_id}` does not explicitly have `{event.permission}`.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            new_mask = current_mask & ~int(permission)
            if new_mask == 0:
                self.permission_repository.remove_by_user_and_thread(
                    discord_user_id=event.target_user_id,
                    thread_id=thread.thread_id,
                )
            else:
                self.permission_repository.upsert_permissions(
                    discord_user_id=event.target_user_id,
                    thread_id=thread.thread_id,
                    permissions=new_mask,
                )
            return DiscordCommandResult(
                title="Permission Revoked",
                message=f"Revoked `{event.permission}` from Discord user `{event.target_user_id}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        raise ValueError("Unsupported action. Use grant, revoke or clear.")
