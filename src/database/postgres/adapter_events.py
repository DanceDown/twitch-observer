"""PostgreSQL repository for external adapter events."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import AdapterEventRecord
from ..repositories import AdapterEventRepository
from ._utils import require_row
from .database import PostgresDatabase

AdapterEventRow = tuple[int, int, str, str, str, str, bool]


@dataclass(slots=True)
class PostgresAdapterEventRepository(AdapterEventRepository):
    """Store and retrieve external adapter event triggers."""

    database: PostgresDatabase

    async def upsert_event(
        self,
        *,
        thread_id: int,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
    ) -> AdapterEventRecord:
        """Create or re-enable an external adapter event trigger."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO adapter_event (thread_id, adapter_key, subject_type, subject_id, event_key, disabled)
                VALUES (%s, %s, %s, %s, %s, FALSE)
                ON CONFLICT (thread_id, adapter_key, subject_type, subject_id, event_key)
                DO UPDATE SET disabled = FALSE
                RETURNING event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                """,
                (thread_id, adapter_key, subject_type, subject_id, event_key),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="adapter_event.upsert_event")
        return self._build_record(row)

    async def get_event(
        self,
        *,
        thread_id: int,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
    ) -> AdapterEventRecord | None:
        """Return one external adapter event trigger by its natural key."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                FROM adapter_event
                WHERE thread_id = %s
                  AND adapter_key = %s
                  AND subject_type = %s
                  AND subject_id = %s
                  AND event_key = %s
                """,
                (thread_id, adapter_key, subject_type, subject_id, event_key),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def list_events_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[AdapterEventRecord]:
        """Return external adapter events configured for one thread."""
        async with self.database.read_cursor() as cursor:
            if include_disabled:
                await cursor.execute(
                    """
                    SELECT event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                    FROM adapter_event
                    WHERE thread_id = %s
                    ORDER BY adapter_key, event_key, subject_id
                    """,
                    (thread_id,),
                )
            else:
                await cursor.execute(
                    """
                    SELECT event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                    FROM adapter_event
                    WHERE thread_id = %s AND disabled = FALSE
                    ORDER BY adapter_key, event_key, subject_id
                    """,
                    (thread_id,),
                )
            rows = await cursor.fetchall()
        return [self._build_record(row) for row in rows]

    async def list_matching_events(
        self,
        *,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
        include_disabled: bool = False,
    ) -> list[AdapterEventRecord]:
        """Return adapter events matching an incoming adapter payload."""
        async with self.database.read_cursor() as cursor:
            if include_disabled:
                await cursor.execute(
                    """
                    SELECT event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                    FROM adapter_event
                    WHERE adapter_key = %s
                      AND subject_type = %s
                      AND subject_id = %s
                      AND event_key = %s
                    ORDER BY thread_id, event_id
                    """,
                    (adapter_key, subject_type, subject_id, event_key),
                )
            else:
                await cursor.execute(
                    """
                    SELECT event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                    FROM adapter_event
                    WHERE adapter_key = %s
                      AND subject_type = %s
                      AND subject_id = %s
                      AND event_key = %s
                      AND disabled = FALSE
                    ORDER BY thread_id, event_id
                    """,
                    (adapter_key, subject_type, subject_id, event_key),
                )
            rows = await cursor.fetchall()
        return [self._build_record(row) for row in rows]

    @staticmethod
    def _build_record(row: AdapterEventRow) -> AdapterEventRecord:
        return AdapterEventRecord(
            event_id=int(row[0]),
            thread_id=int(row[1]),
            adapter_key=str(row[2]),
            subject_type=str(row[3]),
            subject_id=str(row[4]),
            event_key=str(row[5]),
            disabled=bool(row[6]),
        )
