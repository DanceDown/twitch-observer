"""PostgreSQL repository for external adapter event actions."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import AdapterEventActionRecord, AdapterEventRecord
from ..repositories import AdapterEventActionRepository
from ._utils import require_row
from .adapter_events import PostgresAdapterEventRepository
from .database import PostgresDatabase

AdapterEventActionRow = tuple[int, str, str | None, bool, str | None, bool]
AdapterEventActionWithEventRow = tuple[int, int, str, str, str, str, bool, int, str, str | None, bool, str | None, bool]


@dataclass(slots=True)
class PostgresAdapterEventActionRepository(AdapterEventActionRepository):
    """Store and retrieve follow-up actions for external adapter events."""

    database: PostgresDatabase

    async def upsert_action(
        self,
        *,
        event_id: int,
        action_type: str,
        message_template: str | None,
        reply_as_reply: bool,
    ) -> AdapterEventActionRecord:
        """Create, update, and re-enable one adapter-event action."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO adapter_event_action (event_id, action_type, message_template, reply_as_reply, color, disabled)
                VALUES (%s, %s, %s, %s, NULL, FALSE)
                ON CONFLICT (event_id, action_type)
                DO UPDATE SET
                    message_template = EXCLUDED.message_template,
                    reply_as_reply = EXCLUDED.reply_as_reply,
                    disabled = FALSE
                RETURNING event_id, action_type, message_template, reply_as_reply, color, disabled
                """,
                (event_id, action_type, message_template, reply_as_reply),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="adapter_event_action.upsert_action")
        return self._build_record(row)

    async def get_action(self, *, event_id: int, action_type: str) -> AdapterEventActionRecord | None:
        """Return one action configured for an adapter event."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT event_id, action_type, message_template, reply_as_reply, color, disabled
                FROM adapter_event_action
                WHERE event_id = %s AND action_type = %s
                """,
                (event_id, action_type),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def remove_action(self, *, event_id: int, action_type: str) -> AdapterEventActionRecord | None:
        """Delete and return one action configured for an adapter event."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM adapter_event_action
                WHERE event_id = %s AND action_type = %s
                RETURNING event_id, action_type, message_template, reply_as_reply, color, disabled
                """,
                (event_id, action_type),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def set_action_disabled(
        self,
        *,
        event_id: int,
        action_type: str,
        disabled: bool,
    ) -> AdapterEventActionRecord | None:
        """Enable or disable one action configured for an adapter event."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE adapter_event_action
                SET disabled = %s
                WHERE event_id = %s AND action_type = %s
                RETURNING event_id, action_type, message_template, reply_as_reply, color, disabled
                """,
                (disabled, event_id, action_type),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def set_action_color(
        self,
        *,
        event_id: int,
        action_type: str,
        color: str | None,
    ) -> AdapterEventActionRecord | None:
        """Set or clear the embed color on an adapter-event action."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE adapter_event_action
                SET color = %s
                WHERE event_id = %s AND action_type = %s
                RETURNING event_id, action_type, message_template, reply_as_reply, color, disabled
                """,
                (color, event_id, action_type),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def list_actions_for_event(
        self,
        event_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[AdapterEventActionRecord]:
        """Return actions for one adapter event."""
        async with self.database.read_cursor() as cursor:
            if include_disabled:
                await cursor.execute(
                    """
                    SELECT event_id, action_type, message_template, reply_as_reply, color, disabled
                    FROM adapter_event_action
                    WHERE event_id = %s
                    ORDER BY action_type
                    """,
                    (event_id,),
                )
            else:
                await cursor.execute(
                    """
                    SELECT event_id, action_type, message_template, reply_as_reply, color, disabled
                    FROM adapter_event_action
                    WHERE event_id = %s AND disabled = FALSE
                    ORDER BY action_type
                    """,
                    (event_id,),
                )
            rows: list[AdapterEventActionRow] = await cursor.fetchall()
        return [self._build_record(row) for row in rows]

    async def list_actions_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[tuple[AdapterEventRecord, AdapterEventActionRecord]]:
        """Return a thread's adapter-event actions with their event records."""
        async with self.database.read_cursor() as cursor:
            if include_disabled:
                await cursor.execute(
                    """
                    SELECT ae.event_id, ae.thread_id, ae.adapter_key, ae.subject_type, ae.subject_id, ae.event_key, ae.disabled,
                           aea.event_id, aea.action_type, aea.message_template, aea.reply_as_reply, aea.color, aea.disabled
                    FROM adapter_event ae
                    JOIN adapter_event_action aea ON aea.event_id = ae.event_id
                    WHERE ae.thread_id = %s
                    ORDER BY ae.adapter_key, ae.event_key, ae.subject_id, aea.action_type
                    """,
                    (thread_id,),
                )
            else:
                await cursor.execute(
                    """
                    SELECT ae.event_id, ae.thread_id, ae.adapter_key, ae.subject_type, ae.subject_id, ae.event_key, ae.disabled,
                           aea.event_id, aea.action_type, aea.message_template, aea.reply_as_reply, aea.color, aea.disabled
                    FROM adapter_event ae
                    JOIN adapter_event_action aea ON aea.event_id = ae.event_id
                    WHERE ae.thread_id = %s
                      AND ae.disabled = FALSE
                      AND aea.disabled = FALSE
                    ORDER BY ae.adapter_key, ae.event_key, ae.subject_id, aea.action_type
                    """,
                    (thread_id,),
                )
            rows: list[AdapterEventActionWithEventRow] = await cursor.fetchall()
        results: list[tuple[AdapterEventRecord, AdapterEventActionRecord]] = []
        for row in rows:
            event_record = PostgresAdapterEventRepository._build_record(row[:7])
            action_record = self._build_record(row[7:])
            results.append((event_record, action_record))
        return results

    @staticmethod
    def _build_record(row: AdapterEventActionRow) -> AdapterEventActionRecord:
        return AdapterEventActionRecord(
            event_id=int(row[0]),
            action_type=str(row[1]),
            message_template=None if row[2] is None else str(row[2]),
            reply_as_reply=bool(row[3]),
            color=None if row[4] is None else str(row[4]),
            disabled=bool(row[5]),
        )
