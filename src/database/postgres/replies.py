"""PostgreSQL repository for pattern-bound auto replies."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import ReplyRecord
from ..repositories import ReplyRepository
from .database import PostgresDatabase

ReplyRow = tuple[int, int, str, bool, bool]
PatternIdRow = tuple[int]


@dataclass(slots=True)
class PostgresReplyRepository(ReplyRepository):
    """Store and retrieve auto-replies attached to patterns."""

    database: PostgresDatabase

    async def get_by_pattern(self, *, thread_id: int, pattern_id: int) -> ReplyRecord | None:
        """Return the auto-reply configured for one pattern."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, pattern_id, reply_message, reply_as_reply, disabled
                FROM reply
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    async def add_reply(
        self,
        *,
        thread_id: int,
        pattern_id: int,
        reply_message: str,
        reply_as_reply: bool,
    ) -> ReplyRecord | None:
        """Insert an auto-reply when the pattern does not have one yet."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO reply (thread_id, pattern_id, reply_message, reply_as_reply, disabled)
                VALUES (%s, %s, %s, %s, FALSE)
                ON CONFLICT (thread_id, pattern_id) DO NOTHING
                RETURNING thread_id, pattern_id, reply_message, reply_as_reply, disabled
                """,
                (thread_id, pattern_id, reply_message, reply_as_reply),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    async def remove_reply(self, *, thread_id: int, pattern_id: int) -> ReplyRecord | None:
        """Delete and return the auto-reply configured for one pattern."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM reply
                WHERE thread_id = %s AND pattern_id = %s
                RETURNING thread_id, pattern_id, reply_message, reply_as_reply, disabled
                """,
                (thread_id, pattern_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    async def set_reply_disabled(self, *, thread_id: int, pattern_id: int, disabled: bool) -> ReplyRecord | None:
        """Enable or disable the auto-reply configured for one pattern."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE reply
                SET disabled = %s
                WHERE thread_id = %s AND pattern_id = %s
                RETURNING thread_id, pattern_id, reply_message, reply_as_reply, disabled
                """,
                (disabled, thread_id, pattern_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    async def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ReplyRecord]:
        """Return auto-replies configured in one thread."""
        async with self.database.read_cursor() as cursor:
            if include_disabled:
                await cursor.execute(
                    """
                    SELECT thread_id, pattern_id, reply_message, reply_as_reply, disabled
                    FROM reply
                    WHERE thread_id = %s
                    ORDER BY pattern_id
                    """,
                    (thread_id,),
                )
            else:
                await cursor.execute(
                    """
                    SELECT thread_id, pattern_id, reply_message, reply_as_reply, disabled
                    FROM reply
                    WHERE thread_id = %s AND disabled = FALSE
                    ORDER BY pattern_id
                    """,
                    (thread_id,),
                )
            rows = await cursor.fetchall()
        return [self._build_reply_record(row) for row in rows]

    async def disable_replies_for_thread(self, thread_id: int) -> int:
        """Disable all enabled auto-replies in one thread."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE reply
                SET disabled = TRUE
                WHERE thread_id = %s AND disabled = FALSE
                RETURNING pattern_id
                """,
                (thread_id,),
            )
            rows: list[PatternIdRow] = await cursor.fetchall()
        return len(rows)

    async def enable_replies_for_thread(self, thread_id: int) -> int:
        """Enable all disabled auto-replies in one thread."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE reply
                SET disabled = FALSE
                WHERE thread_id = %s AND disabled = TRUE
                RETURNING pattern_id
                """,
                (thread_id,),
            )
            rows: list[PatternIdRow] = await cursor.fetchall()
        return len(rows)

    @staticmethod
    def _build_reply_record(row: ReplyRow) -> ReplyRecord:
        return ReplyRecord(
            thread_id=int(row[0]),
            pattern_id=int(row[1]),
            reply_message=row[2],
            reply_as_reply=row[3],
            disabled=row[4],
        )
