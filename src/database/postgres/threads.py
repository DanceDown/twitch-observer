"""PostgreSQL repositories for thread-scoped observer state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..records import ChannelRecord, ThreadRecord, TrackedChannelStateRecord, TrackedUserRecord
from ..repositories import ChannelRepository, ThreadRepository, TrackedUserRepository
from ._utils import require_row
from .database import PostgresDatabase


@dataclass(slots=True)
class PostgresThreadRepository(ThreadRepository):
    """Store and retrieve thread roots in PostgreSQL."""

    database: PostgresDatabase

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                FROM thread
                WHERE discord_channel_id = %s
                """,
                (discord_channel_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            language=row[3],
            enabled=row[4],
            color=row[5],
            account_id=row[6],
        )

    async def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                FROM thread
                WHERE owner_id = %s
                ORDER BY thread_id
                """,
                (owner_id,),
            )
            rows = await cursor.fetchall()
        return [
            ThreadRecord(
                thread_id=row[0],
                owner_id=row[1],
                discord_channel_id=row[2],
                language=row[3],
                enabled=row[4],
                color=row[5],
                account_id=row[6],
            )
            for row in rows
        ]

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                FROM thread
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            language=row[3],
            enabled=row[4],
            color=row[5],
            account_id=row[6],
        )

    def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO thread (owner_id, discord_channel_id)
                VALUES (%s, %s)
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (owner_id, discord_channel_id),
            )
            row = cursor.fetchone()
        row = require_row(row, operation="thread.create")
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            language=row[3],
            enabled=row[4],
            color=row[5],
            account_id=row[6],
        )

    def delete_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM thread
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (discord_channel_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            language=row[3],
            enabled=row[4],
            color=row[5],
            account_id=row[6],
        )

    def set_enabled(self, *, discord_channel_id: int, enabled: bool) -> ThreadRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE thread
                SET enabled = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (enabled, discord_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            language=row[3],
            enabled=row[4],
            color=row[5],
            account_id=row[6],
        )

    def set_color(self, *, discord_channel_id: int, color: str | None) -> ThreadRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE thread
                SET color = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (color, discord_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            language=row[3],
            enabled=row[4],
            color=row[5],
            account_id=row[6],
        )

    def set_account_id(self, *, discord_channel_id: int, account_id: int | None) -> ThreadRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE thread
                SET account_id = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (account_id, discord_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            language=row[3],
            enabled=row[4],
            color=row[5],
            account_id=row[6],
        )

    def set_language(self, *, discord_channel_id: int, language: str) -> ThreadRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE thread
                SET language = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (language, discord_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=row[0],
            owner_id=row[1],
            discord_channel_id=row[2],
            language=row[3],
            enabled=row[4],
            color=row[5],
            account_id=row[6],
        )


@dataclass(slots=True)
class PostgresChannelRepository(ChannelRepository):
    """Store and retrieve per-thread Twitch channel subscriptions."""

    database: PostgresDatabase

    async def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, twitch_channel_id, color, is_live, last_live_status_at
                FROM channel
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return ChannelRecord(
            thread_id=row[0],
            twitch_channel_id=row[1],
            color=row[2],
            is_live=row[3],
            last_live_status_at=row[4].isoformat() if row[4] is not None else None,
        )

    def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO channel (thread_id, twitch_channel_id)
                VALUES (%s, %s)
                ON CONFLICT (thread_id, twitch_channel_id) DO NOTHING
                """,
                (thread_id, twitch_channel_id),
            )

    def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM channel
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )

    def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE channel
                SET color = %s
                WHERE thread_id = %s AND twitch_channel_id = %s
                RETURNING thread_id, twitch_channel_id, color, is_live, last_live_status_at
                """,
                (color, thread_id, twitch_channel_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ChannelRecord(
            thread_id=row[0],
            twitch_channel_id=row[1],
            color=row[2],
            is_live=row[3],
            last_live_status_at=row[4].isoformat() if row[4] is not None else None,
        )

    def set_live_state_for_twitch_channel(
        self,
        *,
        twitch_channel_id: str,
        is_live: bool,
        changed_at: str | None,
    ) -> int:
        effective_changed_at = datetime.fromisoformat(changed_at) if changed_at is not None else datetime.now(UTC)
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE channel
                SET is_live = %s,
                    last_live_status_at = %s
                WHERE twitch_channel_id = %s
                """,
                (is_live, effective_changed_at, twitch_channel_id),
            )
            return cursor.rowcount

    async def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT COUNT(*)
                FROM channel
                WHERE twitch_channel_id = %s
                """,
                (twitch_channel_id,),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="channel.count_threads_by_twitch_channel_id")
        return int(row[0])

    async def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id
                FROM channel
                WHERE twitch_channel_id = %s
                """,
                (twitch_channel_id,),
            )
            rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]

    async def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, twitch_channel_id, color, is_live, last_live_status_at
                FROM channel
                WHERE thread_id = %s
                ORDER BY twitch_channel_id
                """,
                (thread_id,),
            )
            rows = await cursor.fetchall()
        return [
            ChannelRecord(
                thread_id=row[0],
                twitch_channel_id=row[1],
                color=row[2],
                is_live=row[3],
                last_live_status_at=row[4].isoformat() if row[4] is not None else None,
            )
            for row in rows
        ]

    async def list_all_twitch_channel_ids(self) -> list[str]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT DISTINCT twitch_channel_id
                FROM channel
                ORDER BY twitch_channel_id
                """
            )
            rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def list_distinct_channel_states(self) -> list[TrackedChannelStateRecord]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT twitch_channel_id,
                       BOOL_OR(is_live) FILTER (WHERE is_live IS NOT NULL),
                       MAX(last_live_status_at)
                FROM channel
                GROUP BY twitch_channel_id
                ORDER BY twitch_channel_id
                """
            )
            rows = await cursor.fetchall()
        return [
            TrackedChannelStateRecord(
                twitch_channel_id=str(row[0]),
                is_live=row[1],
                last_live_status_at=row[2].isoformat() if row[2] is not None else None,
            )
            for row in rows
        ]


@dataclass(slots=True)
class PostgresTrackedUserRepository(TrackedUserRepository):
    """Store and retrieve per-thread tracked Twitch users."""

    database: PostgresDatabase

    async def get_by_thread_and_twitch_user(self, thread_id: int, twitch_user_id: str) -> TrackedUserRecord | None:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, twitch_user_id
                FROM tracked_user
                WHERE thread_id = %s AND twitch_user_id = %s
                """,
                (thread_id, twitch_user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return TrackedUserRecord(thread_id=row[0], twitch_user_id=row[1])

    def add_user(self, thread_id: int, twitch_user_id: str) -> None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tracked_user (thread_id, twitch_user_id)
                VALUES (%s, %s)
                ON CONFLICT (thread_id, twitch_user_id) DO NOTHING
                """,
                (thread_id, twitch_user_id),
            )

    def remove_user(self, thread_id: int, twitch_user_id: str) -> None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM tracked_user
                WHERE thread_id = %s AND twitch_user_id = %s
                """,
                (thread_id, twitch_user_id),
            )

    async def list_users_for_thread(self, thread_id: int) -> list[TrackedUserRecord]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, twitch_user_id
                FROM tracked_user
                WHERE thread_id = %s
                ORDER BY twitch_user_id
                """,
                (thread_id,),
            )
            rows = await cursor.fetchall()
        return [TrackedUserRecord(thread_id=row[0], twitch_user_id=row[1]) for row in rows]

    async def count_pattern_scope_references(self, *, thread_id: int, twitch_user_id: str) -> int:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT COUNT(*)
                FROM pattern_user_scope
                WHERE thread_id = %s AND twitch_user_id = %s
                """,
                (thread_id, twitch_user_id),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="tracked_user.count_pattern_scope_references")
        return int(row[0])
