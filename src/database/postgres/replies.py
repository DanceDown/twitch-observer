"""PostgreSQL repository for pattern-bound auto replies."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import ReplyRecord
from ..repositories import ReplyRepository
from .database import PostgresDatabase


@dataclass(slots=True)
class PostgresReplyRepository(ReplyRepository):
    """Store and retrieve auto-replies attached to patterns."""

    database: PostgresDatabase

    def get_by_pattern(self, *, thread_id: int, pattern_id: int) -> ReplyRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, pattern_id, reply_message, reply_as_reply, disabled
                FROM reply
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def add_reply(
        self,
        *,
        thread_id: int,
        pattern_id: int,
        reply_message: str,
        reply_as_reply: bool,
    ) -> ReplyRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO reply (thread_id, pattern_id, reply_message, reply_as_reply, disabled)
                VALUES (%s, %s, %s, %s, FALSE)
                ON CONFLICT (thread_id, pattern_id) DO NOTHING
                RETURNING thread_id, pattern_id, reply_message, reply_as_reply, disabled
                """,
                (thread_id, pattern_id, reply_message, reply_as_reply),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def remove_reply(self, *, thread_id: int, pattern_id: int) -> ReplyRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM reply
                WHERE thread_id = %s AND pattern_id = %s
                RETURNING thread_id, pattern_id, reply_message, reply_as_reply, disabled
                """,
                (thread_id, pattern_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def set_reply_disabled(self, *, thread_id: int, pattern_id: int, disabled: bool) -> ReplyRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = %s
                WHERE thread_id = %s AND pattern_id = %s
                RETURNING thread_id, pattern_id, reply_message, reply_as_reply, disabled
                """,
                (disabled, thread_id, pattern_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ReplyRecord]:
        with self.database.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT thread_id, pattern_id, reply_message, reply_as_reply, disabled
                    FROM reply
                    WHERE thread_id = %s
                    ORDER BY pattern_id
                    """,
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT thread_id, pattern_id, reply_message, reply_as_reply, disabled
                    FROM reply
                    WHERE thread_id = %s AND disabled = FALSE
                    ORDER BY pattern_id
                    """,
                    (thread_id,),
                )
            rows = cursor.fetchall()
        return [self._build_reply_record(row) for row in rows]

    def disable_replies_for_thread(self, thread_id: int) -> int:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = TRUE
                WHERE thread_id = %s AND disabled = FALSE
                RETURNING pattern_id
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return len(rows)

    def enable_replies_for_thread(self, thread_id: int) -> int:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = FALSE
                WHERE thread_id = %s AND disabled = TRUE
                RETURNING pattern_id
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return len(rows)

    @staticmethod
    def _build_reply_record(row: tuple) -> ReplyRecord:
        return ReplyRecord(
            thread_id=int(row[0]),
            pattern_id=int(row[1]),
            reply_message=row[2],
            reply_as_reply=row[3],
            disabled=row[4],
        )
