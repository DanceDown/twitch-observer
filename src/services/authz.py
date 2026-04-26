"""Shared authorization helpers for thread-scoped Discord actions."""

from __future__ import annotations

from src.database.connection import ThreadRecord, UserPermissionRepository
from src.utils.permissions import ObserverPermission, has_permission


def thread_has_permission(
    *,
    thread: ThreadRecord,
    requester_id: int,
    permission_repository: UserPermissionRepository | None,
    required_permission: ObserverPermission,
) -> bool:
    """Return whether one requester may perform a thread-scoped action."""
    if thread.owner_id == requester_id:
        return True
    if permission_repository is None:
        return False
    record = permission_repository.get_by_user_and_thread(
        discord_user_id=requester_id,
        thread_id=thread.thread_id,
    )
    if record is None:
        return False
    return has_permission(record.permissions, required_permission)

