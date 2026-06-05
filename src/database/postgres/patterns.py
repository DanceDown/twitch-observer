"""PostgreSQL repository for message-driven patterns."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..records import PatternRecord
from ..repositories import PatternRepository
from ._utils import require_row
from .database import PostgresDatabase


PatternRow = tuple


@dataclass(slots=True)
class PostgresPatternRepository(PatternRepository):
    """Store and retrieve ping/regex rules."""

    database: PostgresDatabase

    async def find_exact_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
    ) -> PatternRecord | None:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s
                  AND regex = %s
                  AND channel_scope_mode = %s
                  AND user_scope_mode = %s
                  AND sub_state = %s
                  AND offline_state = %s
                  AND is_regex = %s
                  AND case_sensitive = %s
                ORDER BY pattern_id
                """,
                (
                    thread_id,
                    regex,
                    channel_scope_mode,
                    user_scope_mode,
                    sub_state,
                    offline_state,
                    is_regex,
                    case_sensitive,
                ),
            )
            rows = await cursor.fetchall()
        patterns = await self._build_patterns_from_rows(rows)
        normalized_scope_ids = tuple(sorted(channel_scope_ids))
        normalized_user_ids = tuple(sorted(user_scope_ids))
        for pattern in patterns:
            if pattern.channel_scope_ids == normalized_scope_ids and pattern.user_scope_ids == normalized_user_ids:
                return pattern
        return None

    async def add_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        disabled: bool,
        priority: int,
    ) -> PatternRecord:
        async with self.database.async_transaction() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO pattern (
                        thread_id, regex, channel_scope_mode, user_scope_mode,
                        sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                        notify, priority
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                    RETURNING thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                              sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                              notify, priority
                    """,
                    (
                        thread_id,
                        regex,
                        channel_scope_mode,
                        user_scope_mode,
                        sub_state,
                        offline_state,
                        is_regex,
                        case_sensitive,
                        color,
                        disabled,
                        priority,
                    ),
                )
                row = require_row(await cursor.fetchone(), operation="pattern.add_pattern")
                persisted_pattern_id = int(row[1])
                if channel_scope_ids:
                    await cursor.executemany(
                        """
                        INSERT INTO pattern_channel_scope (thread_id, pattern_id, twitch_channel_id)
                        VALUES (%s, %s, %s)
                        """,
                        [(thread_id, persisted_pattern_id, twitch_channel_id) for twitch_channel_id in channel_scope_ids],
                    )
                if user_scope_ids:
                    await cursor.executemany(
                        """
                        INSERT INTO pattern_user_scope (thread_id, pattern_id, twitch_user_id)
                        VALUES (%s, %s, %s)
                        """,
                        [(thread_id, persisted_pattern_id, twitch_user_id) for twitch_user_id in user_scope_ids],
                    )
        return self._build_pattern_record(
            row,
            channel_scope_ids=tuple(sorted(channel_scope_ids)),
            user_scope_ids=tuple(sorted(user_scope_ids)),
        )

    async def remove_pattern(self, *, thread_id: int, pattern_id: int) -> None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM pattern
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )

    async def set_pattern_disabled(self, *, thread_id: int, pattern_id: int, disabled: bool) -> PatternRecord | None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE pattern
                SET disabled = %s
                WHERE thread_id = %s AND pattern_id = %s
                RETURNING thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (disabled, thread_id, pattern_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        channel_scope_map, user_scope_map = await self._load_scope_maps(thread_id=thread_id, pattern_ids=(pattern_id,))
        return self._build_pattern_record(
            row,
            channel_scope_ids=channel_scope_map.get(pattern_id, ()),
            user_scope_ids=user_scope_map.get(pattern_id, ()),
        )

    async def set_pattern_priority(self, *, thread_id: int, pattern_id: int, priority: int) -> PatternRecord | None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE pattern
                SET priority = %s
                WHERE thread_id = %s AND pattern_id = %s
                RETURNING thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (priority, thread_id, pattern_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        channel_scope_map, user_scope_map = await self._load_scope_maps(thread_id=thread_id, pattern_ids=(pattern_id,))
        return self._build_pattern_record(
            row,
            channel_scope_ids=channel_scope_map.get(pattern_id, ()),
            user_scope_ids=user_scope_map.get(pattern_id, ()),
        )

    async def update_pattern(
        self,
        *,
        thread_id: int,
        pattern_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        priority: int,
    ) -> PatternRecord | None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE pattern
                SET regex = %s,
                    channel_scope_mode = %s,
                    user_scope_mode = %s,
                    sub_state = %s,
                    offline_state = %s,
                    is_regex = %s,
                    case_sensitive = %s,
                    color = %s,
                    priority = %s
                WHERE thread_id = %s AND pattern_id = %s
                RETURNING thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (
                    regex,
                    channel_scope_mode,
                    user_scope_mode,
                    sub_state,
                    offline_state,
                    is_regex,
                    case_sensitive,
                    color,
                    priority,
                    thread_id,
                    pattern_id,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            await cursor.execute(
                """
                DELETE FROM pattern_channel_scope
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )
            if channel_scope_ids:
                await cursor.executemany(
                    """
                    INSERT INTO pattern_channel_scope (thread_id, pattern_id, twitch_channel_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, pattern_id, twitch_channel_id) for twitch_channel_id in channel_scope_ids],
                )
            await cursor.execute(
                """
                DELETE FROM pattern_user_scope
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )
            if user_scope_ids:
                await cursor.executemany(
                    """
                    INSERT INTO pattern_user_scope (thread_id, pattern_id, twitch_user_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, pattern_id, twitch_user_id) for twitch_user_id in user_scope_ids],
                )
        return self._build_pattern_record(
            row,
            channel_scope_ids=tuple(sorted(channel_scope_ids)),
            user_scope_ids=tuple(sorted(user_scope_ids)),
        )

    async def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s AND disabled = FALSE AND notify = TRUE
                ORDER BY priority DESC, pattern_id
                """,
                (thread_id,),
            )
            rows = await cursor.fetchall()
        return await self._build_patterns_from_rows(rows)

    async def get_pattern_by_id(
        self,
        *,
        thread_id: int,
        pattern_id: int,
    ) -> PatternRecord | None:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        patterns = await self._build_patterns_from_rows([row])
        return patterns[0] if patterns else None

    async def list_patterns_for_thread(
        self,
        thread_id: int,
        *,
        is_regex: bool | None = None,
    ) -> list[PatternRecord]:
        async with self.database.read_cursor() as cursor:
            if is_regex is None:
                await cursor.execute(
                    """
                    SELECT thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                           sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                           notify, priority
                    FROM pattern
                    WHERE thread_id = %s
                    ORDER BY pattern_id
                    """,
                    (thread_id,),
                )
            else:
                await cursor.execute(
                    """
                    SELECT thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                           sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                           notify, priority
                    FROM pattern
                    WHERE thread_id = %s AND is_regex = %s
                    ORDER BY pattern_id
                    """,
                    (thread_id, is_regex),
                )
            rows = await cursor.fetchall()
        return await self._build_patterns_from_rows(rows)

    async def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT COUNT(*)
                FROM pattern_channel_scope
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="pattern.count_channel_scope_references")
        return int(row[0])

    async def _build_patterns_from_rows(self, rows: list[PatternRow]) -> list[PatternRecord]:
        if not rows:
            return []
        thread_id = int(rows[0][0])
        pattern_ids = tuple(int(row[1]) for row in rows)
        channel_scope_map, user_scope_map = await self._load_scope_maps(thread_id=thread_id, pattern_ids=pattern_ids)
        return [
            self._build_pattern_record(
                row,
                channel_scope_ids=channel_scope_map.get(int(row[1]), ()),
                user_scope_ids=user_scope_map.get(int(row[1]), ()),
            )
            for row in rows
        ]

    async def _load_scope_maps(
        self,
        *,
        thread_id: int,
        pattern_ids: tuple[int, ...],
    ) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[str, ...]]]:
        if not pattern_ids:
            return {}, {}
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT pattern_id, twitch_channel_id
                FROM pattern_channel_scope
                WHERE thread_id = %s AND pattern_id = ANY(%s)
                ORDER BY pattern_id, twitch_channel_id
                """,
                (thread_id, list(pattern_ids)),
            )
            channel_rows = await cursor.fetchall()
            await cursor.execute(
                """
                SELECT pattern_id, twitch_user_id
                FROM pattern_user_scope
                WHERE thread_id = %s AND pattern_id = ANY(%s)
                ORDER BY pattern_id, twitch_user_id
                """,
                (thread_id, list(pattern_ids)),
            )
            user_rows = await cursor.fetchall()
        channel_scope_map = self._scope_rows_to_map(channel_rows)
        user_scope_map = self._scope_rows_to_map(user_rows)
        return channel_scope_map, user_scope_map

    @staticmethod
    def _scope_rows_to_map(rows: list[tuple]) -> dict[int, tuple[str, ...]]:
        scope_map: dict[int, list[str]] = defaultdict(list)
        for row in rows:
            scope_map[int(row[0])].append(str(row[1]))
        return {pattern_id: tuple(values) for pattern_id, values in scope_map.items()}

    @staticmethod
    def _build_pattern_record(
        row: PatternRow,
        *,
        channel_scope_ids: tuple[str, ...],
        user_scope_ids: tuple[str, ...],
    ) -> PatternRecord:
        return PatternRecord(
            thread_id=int(row[0]),
            pattern_id=int(row[1]),
            regex=row[2],
            channel_scope_mode=row[3],
            channel_scope_ids=channel_scope_ids,
            user_scope_mode=row[4],
            user_scope_ids=user_scope_ids,
            sub_state=row[5],
            offline_state=row[6],
            is_regex=row[7],
            case_sensitive=row[8],
            color=row[9],
            disabled=row[10],
            notify=row[11],
            priority=int(row[12]),
        )
