"""PostgreSQL repository for message-driven patterns."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import PatternRecord
from ..repositories import PatternRepository
from ._utils import require_row
from .database import PostgresDatabase


@dataclass(slots=True)
class PostgresPatternRepository(PatternRepository):
    """Store and retrieve ping/regex rules."""

    database: PostgresDatabase

    def find_exact_pattern(
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
        with self.database.cursor() as cursor:
            cursor.execute(
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
            rows = cursor.fetchall()
        normalized_scope_ids = tuple(sorted(channel_scope_ids))
        normalized_user_ids = tuple(sorted(user_scope_ids))
        for row in rows:
            pattern = self._build_pattern_record(row)
            if pattern.channel_scope_ids == normalized_scope_ids and pattern.user_scope_ids == normalized_user_ids:
                return pattern
        return None

    def add_pattern(
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
        with self.database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
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
                row = cursor.fetchone()
                persisted_pattern = require_row(row, operation="pattern.add_pattern")
                pattern = self._build_pattern_record(persisted_pattern)
                if channel_scope_ids:
                    cursor.executemany(
                        """
                        INSERT INTO pattern_channel_scope (thread_id, pattern_id, twitch_channel_id)
                        VALUES (%s, %s, %s)
                        """,
                        [(thread_id, pattern.pattern_id, twitch_channel_id) for twitch_channel_id in channel_scope_ids],
                    )
                if user_scope_ids:
                    cursor.executemany(
                        """
                        INSERT INTO pattern_user_scope (thread_id, pattern_id, twitch_user_id)
                        VALUES (%s, %s, %s)
                        """,
                        [(thread_id, pattern.pattern_id, twitch_user_id) for twitch_user_id in user_scope_ids],
                    )
        return self.get_pattern_by_id(thread_id=thread_id, pattern_id=pattern.pattern_id) or pattern

    def remove_pattern(self, *, thread_id: int, pattern_id: int) -> None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM pattern
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )

    def set_pattern_disabled(self, *, thread_id: int, pattern_id: int, disabled: bool) -> PatternRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
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
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_pattern_record(row)

    def set_pattern_priority(self, *, thread_id: int, pattern_id: int, priority: int) -> PatternRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
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
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_pattern_record(row)

    def update_pattern(
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
        with self.database.cursor() as cursor:
            cursor.execute(
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
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                DELETE FROM pattern_channel_scope
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )
            if channel_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_channel_scope (thread_id, pattern_id, twitch_channel_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, pattern_id, twitch_channel_id) for twitch_channel_id in channel_scope_ids],
                )
            cursor.execute(
                """
                DELETE FROM pattern_user_scope
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )
            if user_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_user_scope (thread_id, pattern_id, twitch_user_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, pattern_id, twitch_user_id) for twitch_user_id in user_scope_ids],
                )
        return self._build_pattern_record(row)

    def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        with self.database.cursor() as cursor:
            cursor.execute(
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
            rows = cursor.fetchall()
        return [self._build_pattern_record(row) for row in rows]

    def get_pattern_by_id(
        self,
        *,
        thread_id: int,
        pattern_id: int,
    ) -> PatternRecord | None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s AND pattern_id = %s
                """,
                (thread_id, pattern_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_pattern_record(row)

    def list_patterns_for_thread(
        self,
        thread_id: int,
        *,
        is_regex: bool | None = None,
    ) -> list[PatternRecord]:
        with self.database.cursor() as cursor:
            if is_regex is None:
                cursor.execute(
                    """
                    SELECT thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                           sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                           notify, priority
                    FROM pattern
                    WHERE thread_id = %s
                    ORDER BY priority DESC, pattern_id
                    """,
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                           sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                           notify, priority
                    FROM pattern
                    WHERE thread_id = %s AND is_regex = %s
                    ORDER BY priority DESC, pattern_id
                    """,
                    (thread_id, is_regex),
                )
            rows = cursor.fetchall()
        return [self._build_pattern_record(row) for row in rows]

    def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM pattern_channel_scope
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )
            row = cursor.fetchone()
        row = require_row(row, operation="pattern.count_channel_scope_references")
        return int(row[0])

    def _load_channel_scope_ids(self, *, thread_id: int, pattern_id: int) -> tuple[str, ...]:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT twitch_channel_id
                FROM pattern_channel_scope
                WHERE thread_id = %s AND pattern_id = %s
                ORDER BY twitch_channel_id
                """,
                (thread_id, pattern_id),
            )
            rows = cursor.fetchall()
        return tuple(str(row[0]) for row in rows)

    def _load_user_scope_ids(self, *, thread_id: int, pattern_id: int) -> tuple[str, ...]:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT twitch_user_id
                FROM pattern_user_scope
                WHERE thread_id = %s AND pattern_id = %s
                ORDER BY twitch_user_id
                """,
                (thread_id, pattern_id),
            )
            rows = cursor.fetchall()
        return tuple(str(row[0]) for row in rows)

    def _build_pattern_record(self, row: tuple) -> PatternRecord:
        thread_id = int(row[0])
        pattern_id = int(row[1])
        return PatternRecord(
            thread_id=thread_id,
            pattern_id=pattern_id,
            regex=row[2],
            channel_scope_mode=row[3],
            channel_scope_ids=self._load_channel_scope_ids(thread_id=thread_id, pattern_id=pattern_id),
            user_scope_mode=row[4],
            user_scope_ids=self._load_user_scope_ids(thread_id=thread_id, pattern_id=pattern_id),
            sub_state=row[5],
            offline_state=row[6],
            is_regex=row[7],
            case_sensitive=row[8],
            color=row[9],
            disabled=row[10],
            notify=row[11],
            priority=int(row[12]),
        )
