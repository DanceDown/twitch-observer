"""Business logic for per-thread Discord permission management."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.database.connection import ThreadRepository, UserPermissionRepository
from src.discord_results import build_thread_result, discord_user_mention
from src.events.event_types import (
    ClearPermissionsCommand,
    DiscordCommandResult,
    DiscordResultStyle,
    GrantPermissionsCommand,
    RevokePermissionsCommand,
)
from src.localization import Localizer
from src.services.command_execution import CommandExecutionRunner, ThreadCommandGuards
from src.utils.permissions import ObserverPermission, permissions_mask_from_values

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PermissionCommandService:
    """Handle `/permission` grant/revoke/clear requests."""

    thread_repository: ThreadRepository
    permission_repository: UserPermissionRepository
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    _guards: ThreadCommandGuards = field(init=False, repr=False)
    _runner: CommandExecutionRunner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._guards = ThreadCommandGuards(
            thread_repository=self.thread_repository,
            permission_repository=self.permission_repository,
            account_repository=None,
            localizer=self.localizer,
            not_joined_key="results.permission.not_joined",
        )
        self._runner = CommandExecutionRunner(
            localizer=self.localizer,
            resolve_thread=lambda command: self.thread_repository.get_by_discord_channel_id(command.discord_channel_id),
            validation_error_key="results.permission.validation_error",
            twitch_api_error_key="results.permission.twitch_api_error",
            unexpected_error_key="results.permission.unexpected_error",
        )

    async def handle_grant(self, command: GrantPermissionsCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._grant(command), logger_=logger)

    async def handle_revoke(self, command: RevokePermissionsCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._revoke(command), logger_=logger)

    async def handle_clear(self, command: ClearPermissionsCommand) -> DiscordCommandResult:
        return await self._runner.run(command, lambda: self._clear(command), logger_=logger)

    async def _require_manage_permissions(self, command) -> tuple[object, DiscordCommandResult | None]:
        thread = await self._guards.require_permission(
            command,
            permission=ObserverPermission.MANAGE_PERMISSIONS,
            denial_key="results.permission.permission_denied",
        )
        if isinstance(thread, DiscordCommandResult):
            return None, thread
        if command.target_user_id == thread.owner_id:
            return None, build_thread_result(
                self.localizer,
                "results.permission.owner_locked",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread, None

    async def _clear(self, command: ClearPermissionsCommand) -> DiscordCommandResult:
        thread, denied = await self._require_manage_permissions(command)
        if denied is not None:
            return denied
        removed = await self.permission_repository.remove_by_user_and_thread(
                discord_user_id=command.target_user_id,
                thread_id=thread.thread_id,
            )
        
        return build_thread_result(
            self.localizer,
            "results.permission.cleared" if removed else "results.permission.none_found",
            thread=thread,
            TARGET=f"<@{command.target_user_id}>",
            style=DiscordResultStyle.SUCCESS if removed else DiscordResultStyle.INFO,
            ephemeral=not removed,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    async def _grant(self, command: GrantPermissionsCommand) -> DiscordCommandResult:
        thread, denied = await self._require_manage_permissions(command)
        if denied is not None:
            return denied
        if not command.permissions:
            raise ValueError(self.localizer.text("results.permission.grant_empty_selection", language=thread.language))
        requested_permissions = tuple(dict.fromkeys(command.permissions))
        permission_mask = permissions_mask_from_values(requested_permissions)
        current = await self.permission_repository.get_by_user_and_thread(
                discord_user_id=command.target_user_id,
                thread_id=thread.thread_id,
            )
        
        current_mask = 0 if current is None else current.permissions
        updated = await self.permission_repository.upsert_permissions(
                discord_user_id=command.target_user_id,
                thread_id=thread.thread_id,
                permissions=current_mask | permission_mask,
            )
        
        return build_thread_result(
            self.localizer,
            "results.permission.granted",
            thread=thread,
            TARGET=f"<@{updated.discord_user_id}>",
            PERMISSIONS=[
                self._permission_label("results.permission.granted", value, language=thread.language) for value in requested_permissions
            ],
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    async def _revoke(self, command: RevokePermissionsCommand) -> DiscordCommandResult:
        thread, denied = await self._require_manage_permissions(command)
        if denied is not None:
            return denied
        if not command.permissions:
            raise ValueError(self.localizer.text("results.permission.revoke_empty_selection", language=thread.language))
        requested_permissions = tuple(dict.fromkeys(command.permissions))
        permission_mask = permissions_mask_from_values(requested_permissions)
        current = await self.permission_repository.get_by_user_and_thread(
                discord_user_id=command.target_user_id,
                thread_id=thread.thread_id,
            )
        
        current_mask = 0 if current is None else current.permissions
        matched_mask = current_mask & permission_mask
        if not matched_mask:
            return build_thread_result(
                self.localizer,
                "results.permission.not_granted",
                thread=thread,
                TARGET=f"<@{command.target_user_id}>",
                PERMISSIONS=[
                    self._permission_label("results.permission.not_granted", value, language=thread.language)
                    for value in requested_permissions
                ],
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )
        new_mask = current_mask & ~permission_mask
        if new_mask == 0:
            await self.permission_repository.remove_by_user_and_thread(
                    discord_user_id=command.target_user_id,
                    thread_id=thread.thread_id,
                )
            
        else:
            await self.permission_repository.upsert_permissions(
                    discord_user_id=command.target_user_id,
                    thread_id=thread.thread_id,
                    permissions=new_mask,
                )
            
        return build_thread_result(
            self.localizer,
            "results.permission.revoked",
            thread=thread,
            TARGET=f"<@{command.target_user_id}>",
            PERMISSIONS=[
                self._permission_label("results.permission.revoked", value, language=thread.language) for value in requested_permissions
            ],
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
            USER=discord_user_mention(self.localizer, command.requester_id, language=thread.language),
        )

    def _permission_label(self, scope: str, value: str, *, language: str) -> str:
        return self.localizer.text(f"{scope}.permission_label.{value}", language=language)
