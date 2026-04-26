"""Business logic for per-thread Discord permission management."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.database.connection import ThreadRepository, UserPermissionRepository
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordPermissionRequestedEvent,
    DiscordResultStyle,
    EventType,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission, permissions_mask_from_values

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PermissionCommandService:
    """Handle `/permission` grant/revoke/clear requests."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    permission_repository: UserPermissionRepository
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_PERMISSION_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordPermissionRequestedEvent) -> None:
        try:
            result = self._handle_action(event)
        except ValueError as error:
            result = self._event_result(
                event,
                "results.validation_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling permission command.")
            result = self._event_result(
                event,
                "results.unexpected_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    def _handle_action(self, event: DiscordPermissionRequestedEvent) -> DiscordCommandResult:
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
            required_permission=ObserverPermission.MANAGE_PERMISSIONS,
        ):
            return self.localizer.thread_result(
                "results.permission.permission_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if event.target_user_id == thread.owner_id:
            return self.localizer.thread_result(
                "results.permission.owner_locked",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if event.action == "clear":
            removed = self.permission_repository.remove_by_user_and_thread(
                discord_user_id=event.target_user_id,
                thread_id=thread.thread_id,
            )
            return self.localizer.thread_result(
                "results.permission.cleared" if removed else "results.permission.none_found",
                thread=thread,
                TARGET=f"<@{event.target_user_id}>",
                style=DiscordResultStyle.SUCCESS if removed else DiscordResultStyle.INFO,
                ephemeral=not removed,
            )

        if not event.permissions:
            raise ValueError(self.localizer.text("results.permission.empty_selection", language=thread.language))
        requested_permissions = tuple(dict.fromkeys(event.permissions))
        permission_mask = permissions_mask_from_values(requested_permissions)
        current = self.permission_repository.get_by_user_and_thread(
            discord_user_id=event.target_user_id,
            thread_id=thread.thread_id,
        )
        current_mask = 0 if current is None else current.permissions

        if event.action == "grant":
            new_mask = current_mask | permission_mask
            updated = self.permission_repository.upsert_permissions(
                discord_user_id=event.target_user_id,
                thread_id=thread.thread_id,
                permissions=new_mask,
            )
            rendered = "\n".join(f"- {self._permission_label(value, language=thread.language)}" for value in requested_permissions)
            return self.localizer.thread_result(
                "results.permission.granted",
                thread=thread,
                TARGET=f"<@{updated.discord_user_id}>",
                PERMISSIONS=rendered,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "revoke":
            matched_mask = current_mask & permission_mask
            if not matched_mask:
                rendered = "\n".join(f"- {self._permission_label(value, language=thread.language)}" for value in requested_permissions)
                return self.localizer.thread_result(
                    "results.permission.not_granted",
                    thread=thread,
                    TARGET=f"<@{event.target_user_id}>",
                    PERMISSIONS=rendered,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            new_mask = current_mask & ~permission_mask
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
            rendered = "\n".join(f"- {self._permission_label(value, language=thread.language)}" for value in requested_permissions)
            return self.localizer.thread_result(
                "results.permission.revoked",
                thread=thread,
                TARGET=f"<@{event.target_user_id}>",
                PERMISSIONS=rendered,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        raise ValueError(self.localizer.text("results.permission.unsupported_action", language=thread.language))

    def _permission_label(self, value: str, *, language: str) -> str:
        try:
            return self.localizer.text(f"show.permission.{value}", language=language)
        except ValueError:
            return value.replace("_", " ").capitalize()

    def _event_result(
        self,
        event: DiscordPermissionRequestedEvent,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        return self.localizer.thread_result(key, thread=thread, style=style, ephemeral=ephemeral, **placeholders)

