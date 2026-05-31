"""PostgreSQL repository for external adapter event actions."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import AdapterEventActionRecord, AdapterEventRecord
from ..repositories import AdapterEventActionRepository
from .adapter_events import PostgresAdapterEventRepository
from ._utils import require_row
from .database import PostgresDatabase


@dataclass(slots=True)
class PostgresAdapterEventActionRepository(AdapterEventActionRepository):
    """Store and retrieve follow-up actions for external adapter events."""

    database: PostgresDatabase

    def upsert_action(
        self,
        *,
        event_id: int,
        action_type: str,
        message_template: str | None,
        reply_as_reply: bool,
    ) -> AdapterEventActionRecord:
        with self.database.cursor() as cursor:
            cursor.execute(
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
            row = cursor.fetchone()
        row = require_row(row, operation="adapter_event_action.upsert_action")
        return self._build_record(row)

    def get_action(self, *, event_id: int, action_type: str) -> AdapterEventActionRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_id, action_type, message_template, reply_as_reply, color, disabled
                FROM adapter_event_action
                WHERE event_id = %s AND action_type = %s
                """,
                (event_id, action_type),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def remove_action(self, *, event_id: int, action_type: str) -> AdapterEventActionRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM adapter_event_action
                WHERE event_id = %s AND action_type = %s
                RETURNING event_id, action_type, message_template, reply_as_reply, color, disabled
                """,
                (event_id, action_type),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def set_action_disabled(
        self,
        *,
        event_id: int,
        action_type: str,
        disabled: bool,
    ) -> AdapterEventActionRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_event_action
                SET disabled = %s
                WHERE event_id = %s AND action_type = %s
                RETURNING event_id, action_type, message_template, reply_as_reply, color, disabled
                """,
                (disabled, event_id, action_type),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def set_action_color(
        self,
        *,
        event_id: int,
        action_type: str,
        color: str | None,
    ) -> AdapterEventActionRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_event_action
                SET color = %s
                WHERE event_id = %s AND action_type = %s
                RETURNING event_id, action_type, message_template, reply_as_reply, color, disabled
                """,
                (color, event_id, action_type),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def list_actions_for_event(
        self,
        event_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[AdapterEventActionRecord]:
        with self.database.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT event_id, action_type, message_template, reply_as_reply, color, disabled
                    FROM adapter_event_action
                    WHERE event_id = %s
                    ORDER BY action_type
                    """,
                    (event_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT event_id, action_type, message_template, reply_as_reply, color, disabled
                    FROM adapter_event_action
                    WHERE event_id = %s AND disabled = FALSE
                    ORDER BY action_type
                    """,
                    (event_id,),
                )
            rows = cursor.fetchall()
        return [self._build_record(row) for row in rows]

    def list_actions_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[tuple[AdapterEventRecord, AdapterEventActionRecord]]:
        with self.database.cursor() as cursor:
            if include_disabled:
                cursor.execute(
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
                cursor.execute(
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
            rows = cursor.fetchall()
        results: list[tuple[AdapterEventRecord, AdapterEventActionRecord]] = []
        for row in rows:
            event_record = PostgresAdapterEventRepository._build_record(row[:7])
            action_record = self._build_record(row[7:])
            results.append((event_record, action_record))
        return results

    @staticmethod
    def _build_record(row: tuple) -> AdapterEventActionRecord:
        return AdapterEventActionRecord(
            event_id=int(row[0]),
            action_type=str(row[1]),
            message_template=None if row[2] is None else str(row[2]),
            reply_as_reply=bool(row[3]),
            color=None if row[4] is None else str(row[4]),
            disabled=bool(row[5]),
        )
