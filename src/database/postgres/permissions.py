from __future__ import annotations

"""PostgreSQL permission persistence."""

from dataclasses import dataclass

from ..records import UserPermissionRecord
from ..repositories import UserPermissionRepository
from .database import PostgresDatabase


@dataclass(slots=True)
class PostgresUserPermissionRepository(UserPermissionRepository):
    """Store and retrieve additional per-thread Discord permission grants."""

    database: PostgresDatabase

    def get_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> UserPermissionRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT discord_user_id, thread_id, permissions
                FROM user_permissions
                WHERE discord_user_id = %s AND thread_id = %s
                """,
                (discord_user_id, thread_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return UserPermissionRecord(discord_user_id=int(row[0]), thread_id=int(row[1]), permissions=int(row[2]))

    def upsert_permissions(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
        permissions: int,
    ) -> UserPermissionRecord:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_permissions (discord_user_id, thread_id, permissions)
                VALUES (%s, %s, %s)
                ON CONFLICT (discord_user_id, thread_id)
                DO UPDATE SET permissions = EXCLUDED.permissions
                RETURNING discord_user_id, thread_id, permissions
                """,
                (discord_user_id, thread_id, permissions),
            )
            row = cursor.fetchone()
        assert row is not None
        return UserPermissionRecord(discord_user_id=int(row[0]), thread_id=int(row[1]), permissions=int(row[2]))

    def remove_by_user_and_thread(self, *, discord_user_id: int, thread_id: int) -> bool:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM user_permissions
                WHERE discord_user_id = %s AND thread_id = %s
                RETURNING discord_user_id
                """,
                (discord_user_id, thread_id),
            )
            row = cursor.fetchone()
        return row is not None

    def list_for_thread(self, *, thread_id: int) -> list[UserPermissionRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT discord_user_id, thread_id, permissions
                FROM user_permissions
                WHERE thread_id = %s
                ORDER BY discord_user_id
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return [
            UserPermissionRecord(discord_user_id=int(row[0]), thread_id=int(row[1]), permissions=int(row[2]))
            for row in rows
        ]

