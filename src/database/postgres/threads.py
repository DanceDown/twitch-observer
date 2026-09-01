"""PostgreSQL repositories for thread-scoped observer state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..records import ChannelRecord, ThreadRecord, TrackedChannelStateRecord, TrackedUserRecord
from ..repositories import ChannelRepository, ThreadRepository, TrackedUserRepository
from ._utils import require_row
from .database import PostgresDatabase

ThreadRow = tuple[int, int, int, str, bool, str | None, int | None]
ChannelRow = tuple[int, str, str | None, bool | None, datetime | None]
TrackedChannelStateRow = tuple[str, bool | None, datetime | None]
TrackedUserRow = tuple[int, str]


@dataclass(slots=True)
class PostgresThreadRepository(ThreadRepository):
    """Store and retrieve thread roots in PostgreSQL."""

    database: PostgresDatabase

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        """Return the thread root configured for one Discord channel ID."""
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
        return self._build_thread_record(row)

    async def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:
        """Return thread roots owned by one Discord user."""
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
        return [self._build_thread_record(row) for row in rows]

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        """Return the thread root for one internal thread ID."""
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
        return self._build_thread_record(row)

    async def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
        """Create and return a thread root with default configuration."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO thread (owner_id, discord_channel_id)
                VALUES (%s, %s)
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (owner_id, discord_channel_id),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="thread.create")
        return self._build_thread_record(row)

    async def delete_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        """Delete a thread root and remove now-unused shared channel state."""
        async with self.database.async_transaction() as connection, connection.cursor() as cursor:
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

            await cursor.execute(
                """
                SELECT twitch_channel_id
                FROM channel
                WHERE thread_id = %s
                ORDER BY twitch_channel_id
                """,
                (row[0],),
            )
            removed_channel_rows = await cursor.fetchall()
            removed_channel_ids = [str(channel_row[0]) for channel_row in removed_channel_rows]

            await cursor.execute(
                """
                DELETE FROM thread
                WHERE discord_channel_id = %s
                """,
                (discord_channel_id,),
            )

            if removed_channel_ids:
                await cursor.execute(
                    """
                    DELETE FROM tracked_channel_state AS tcs
                    WHERE tcs.twitch_channel_id = ANY(%s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM channel AS c
                          WHERE c.twitch_channel_id = tcs.twitch_channel_id
                      )
                    """,
                    (removed_channel_ids,),
                )
        return self._build_thread_record(row)

    async def set_enabled(self, *, discord_channel_id: int, enabled: bool) -> ThreadRecord | None:
        """Enable or disable the configured thread for one Discord channel."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE thread
                SET enabled = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (enabled, discord_channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_thread_record(row)

    async def set_color(self, *, discord_channel_id: int, color: str | None) -> ThreadRecord | None:
        """Set or clear the default embed color for one thread."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE thread
                SET color = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (color, discord_channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_thread_record(row)

    async def set_account_id(self, *, discord_channel_id: int, account_id: int | None) -> ThreadRecord | None:
        """Attach or detach the linked Twitch account for one thread."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE thread
                SET account_id = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (account_id, discord_channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_thread_record(row)

    async def set_language(self, *, discord_channel_id: int, language: str) -> ThreadRecord | None:
        """Set the localization language for one thread."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE thread
                SET language = %s
                WHERE discord_channel_id = %s
                RETURNING thread_id, owner_id, discord_channel_id, language, enabled, color, account_id
                """,
                (language, discord_channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_thread_record(row)

    @staticmethod
    def _build_thread_record(row: ThreadRow) -> ThreadRecord:
        return ThreadRecord(
            thread_id=int(row[0]),
            owner_id=int(row[1]),
            discord_channel_id=int(row[2]),
            language=row[3],
            enabled=bool(row[4]),
            color=row[5],
            account_id=row[6],
        )


@dataclass(slots=True)
class PostgresChannelRepository(ChannelRepository):
    """Store and retrieve per-thread Twitch channel subscriptions."""

    database: PostgresDatabase

    async def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        """Return one Twitch channel subscription joined with live state."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT c.thread_id, c.twitch_channel_id, c.color, tcs.is_live, tcs.last_live_status_at
                FROM channel AS c
                LEFT JOIN tracked_channel_state AS tcs
                  ON tcs.twitch_channel_id = c.twitch_channel_id
                WHERE c.thread_id = %s AND c.twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_channel_record(row)

    async def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        """Subscribe a thread to a Twitch channel and ensure shared state exists."""
        async with self.database.async_transaction() as connection, connection.cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO channel (thread_id, twitch_channel_id)
                VALUES (%s, %s)
                ON CONFLICT (thread_id, twitch_channel_id) DO NOTHING
                """,
                (thread_id, twitch_channel_id),
            )
            await cursor.execute(
                """
                INSERT INTO tracked_channel_state (twitch_channel_id)
                VALUES (%s)
                ON CONFLICT (twitch_channel_id) DO NOTHING
                """,
                (twitch_channel_id,),
            )

    async def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        """Unsubscribe a thread and drop shared state when no thread uses it."""
        async with self.database.async_transaction() as connection, connection.cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM channel
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )
            if cursor.rowcount <= 0:
                return
            await cursor.execute(
                """
                DELETE FROM tracked_channel_state AS tcs
                WHERE tcs.twitch_channel_id = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM channel AS c
                      WHERE c.twitch_channel_id = %s
                  )
                """,
                (twitch_channel_id, twitch_channel_id),
            )

    async def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:
        """Set or clear the color override for one subscribed Twitch channel."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE channel
                SET color = %s
                WHERE thread_id = %s AND twitch_channel_id = %s
                RETURNING thread_id
                """,
                (color, thread_id, twitch_channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return await self.get_by_thread_and_twitch_channel(thread_id, twitch_channel_id)

    async def set_live_state_for_twitch_channel(
        self,
        *,
        twitch_channel_id: str,
        is_live: bool,
        changed_at: str | None,
    ) -> int:
        """Upsert live state only when at least one thread tracks the channel."""
        effective_changed_at = datetime.fromisoformat(changed_at) if changed_at is not None else datetime.now(UTC)
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO tracked_channel_state (twitch_channel_id, is_live, last_live_status_at)
                SELECT %s, %s, %s
                WHERE EXISTS (
                    SELECT 1
                    FROM channel
                    WHERE twitch_channel_id = %s
                )
                ON CONFLICT (twitch_channel_id) DO UPDATE
                SET is_live = EXCLUDED.is_live,
                    last_live_status_at = EXCLUDED.last_live_status_at
                """,
                (twitch_channel_id, is_live, effective_changed_at, twitch_channel_id),
            )
            return cursor.rowcount

    async def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        """Count thread subscriptions for a Twitch channel ID."""
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
        """Return thread IDs subscribed to one Twitch channel ID."""
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
        """Return all Twitch channel subscriptions for one thread."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT c.thread_id, c.twitch_channel_id, c.color, tcs.is_live, tcs.last_live_status_at
                FROM channel AS c
                LEFT JOIN tracked_channel_state AS tcs
                  ON tcs.twitch_channel_id = c.twitch_channel_id
                WHERE c.thread_id = %s
                ORDER BY c.twitch_channel_id
                """,
                (thread_id,),
            )
            rows = await cursor.fetchall()
        return [self._build_channel_record(row) for row in rows]

    async def list_all_twitch_channel_ids(self) -> list[str]:
        """Return all distinct Twitch channel IDs subscribed by any thread."""
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
        """Return distinct tracked Twitch channel IDs with their live state."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT tracked.twitch_channel_id, tcs.is_live, tcs.last_live_status_at
                FROM (
                    SELECT DISTINCT twitch_channel_id
                    FROM channel
                ) AS tracked
                LEFT JOIN tracked_channel_state AS tcs
                  ON tcs.twitch_channel_id = tracked.twitch_channel_id
                ORDER BY tracked.twitch_channel_id
                """
            )
            rows = await cursor.fetchall()
        return [self._build_tracked_channel_state_record(row) for row in rows]

    @staticmethod
    def _build_channel_record(row: ChannelRow) -> ChannelRecord:
        return ChannelRecord(
            thread_id=int(row[0]),
            twitch_channel_id=str(row[1]),
            color=row[2],
            is_live=row[3],
            last_live_status_at=row[4].isoformat() if row[4] is not None else None,
        )

    @staticmethod
    def _build_tracked_channel_state_record(row: TrackedChannelStateRow) -> TrackedChannelStateRecord:
        return TrackedChannelStateRecord(
            twitch_channel_id=str(row[0]),
            is_live=row[1],
            last_live_status_at=row[2].isoformat() if row[2] is not None else None,
        )


@dataclass(slots=True)
class PostgresTrackedUserRepository(TrackedUserRepository):
    """Store and retrieve per-thread tracked Twitch users."""

    database: PostgresDatabase

    async def get_by_thread_and_twitch_user(self, thread_id: int, twitch_user_id: str) -> TrackedUserRecord | None:
        """Return one tracked Twitch user inside a thread."""
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
        return self._build_record(row)

    async def add_user(self, thread_id: int, twitch_user_id: str) -> None:
        """Track a Twitch user in one thread."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO tracked_user (thread_id, twitch_user_id)
                VALUES (%s, %s)
                ON CONFLICT (thread_id, twitch_user_id) DO NOTHING
                """,
                (thread_id, twitch_user_id),
            )

    async def remove_user(self, thread_id: int, twitch_user_id: str) -> None:
        """Stop tracking a Twitch user in one thread."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM tracked_user
                WHERE thread_id = %s AND twitch_user_id = %s
                """,
                (thread_id, twitch_user_id),
            )

    async def list_users_for_thread(self, thread_id: int) -> list[TrackedUserRecord]:
        """Return all tracked Twitch users for one thread."""
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
        return [self._build_record(row) for row in rows]

    async def count_pattern_scope_references(self, *, thread_id: int, twitch_user_id: str) -> int:
        """Count pattern scopes that still reference a tracked Twitch user."""
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

    @staticmethod
    def _build_record(row: TrackedUserRow) -> TrackedUserRecord:
        return TrackedUserRecord(thread_id=int(row[0]), twitch_user_id=str(row[1]))
