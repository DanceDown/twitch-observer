from __future__ import annotations

"""PostgreSQL repositories for patterns, replies, and event actions."""

from dataclasses import dataclass

from ..records import AdapterEventActionRecord, AdapterEventRecord, PatternRecord, ReplyRecord
from ..repositories import AdapterEventActionRepository, AdapterEventRepository, PatternRepository, ReplyRepository
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(MAX(p_index), 0) + 1
                FROM pattern
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            next_index_row = cursor.fetchone()
            next_index = int(next_index_row[0]) if next_index_row is not None else 1
            cursor.execute(
                """
                INSERT INTO pattern (
                    thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                    sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                    notify, priority
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                RETURNING thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (
                    thread_id,
                    next_index,
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
            if channel_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_channel_scope (thread_id, p_index, twitch_channel_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, next_index, twitch_channel_id) for twitch_channel_id in channel_scope_ids],
                )
            if user_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_user_scope (thread_id, p_index, twitch_user_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, next_index, twitch_user_id) for twitch_user_id in user_scope_ids],
                )
        assert row is not None
        return self._build_pattern_record(row)

    def remove_pattern(self, *, thread_id: int, p_index: int) -> None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM pattern
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )

    def set_pattern_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> PatternRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pattern
                SET disabled = %s
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (disabled, thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_pattern_record(row)

    def set_pattern_priority(self, *, thread_id: int, p_index: int, priority: int) -> PatternRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pattern
                SET priority = %s
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                          sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                          notify, priority
                """,
                (priority, thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_pattern_record(row)

    def update_pattern(
        self,
        *,
        thread_id: int,
        p_index: int,
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
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
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
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
                    p_index,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                DELETE FROM pattern_channel_scope
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )
            if channel_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_channel_scope (thread_id, p_index, twitch_channel_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, p_index, twitch_channel_id) for twitch_channel_id in channel_scope_ids],
                )
            cursor.execute(
                """
                DELETE FROM pattern_user_scope
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )
            if user_scope_ids:
                cursor.executemany(
                    """
                    INSERT INTO pattern_user_scope (thread_id, p_index, twitch_user_id)
                    VALUES (%s, %s, %s)
                    """,
                    [(thread_id, p_index, twitch_user_id) for twitch_user_id in user_scope_ids],
                )
        return self._build_pattern_record(row)

    def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s AND disabled = FALSE AND notify = TRUE
                ORDER BY priority DESC, p_index
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return [self._build_pattern_record(row) for row in rows]

    def get_pattern_by_id(
        self,
        *,
        thread_id: int,
        p_index: int,
    ) -> PatternRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                       sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                       notify, priority
                FROM pattern
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if is_regex is None:
                cursor.execute(
                    """
                    SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                           sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                           notify, priority
                    FROM pattern
                    WHERE thread_id = %s
                    ORDER BY priority DESC, p_index
                    """,
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT thread_id, p_index, regex, channel_scope_mode, user_scope_mode,
                           sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                           notify, priority
                    FROM pattern
                    WHERE thread_id = %s AND is_regex = %s
                    ORDER BY priority DESC, p_index
                    """,
                    (thread_id, is_regex),
                )
            rows = cursor.fetchall()
        return [self._build_pattern_record(row) for row in rows]

    def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM pattern_channel_scope
                WHERE thread_id = %s AND twitch_channel_id = %s
                """,
                (thread_id, twitch_channel_id),
            )
            row = cursor.fetchone()
        assert row is not None
        return int(row[0])

    def _load_channel_scope_ids(self, *, thread_id: int, p_index: int) -> tuple[str, ...]:
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT twitch_channel_id
                FROM pattern_channel_scope
                WHERE thread_id = %s AND p_index = %s
                ORDER BY twitch_channel_id
                """,
                (thread_id, p_index),
            )
            rows = cursor.fetchall()
        return tuple(str(row[0]) for row in rows)

    def _load_user_scope_ids(self, *, thread_id: int, p_index: int) -> tuple[str, ...]:
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT twitch_user_id
                FROM pattern_user_scope
                WHERE thread_id = %s AND p_index = %s
                ORDER BY twitch_user_id
                """,
                (thread_id, p_index),
            )
            rows = cursor.fetchall()
        return tuple(str(row[0]) for row in rows)

    def _build_pattern_record(self, row: tuple) -> PatternRecord:
        thread_id = int(row[0])
        p_index = int(row[1])
        return PatternRecord(
            thread_id=thread_id,
            p_index=p_index,
            regex=row[2],
            channel_scope_mode=row[3],
            channel_scope_ids=self._load_channel_scope_ids(thread_id=thread_id, p_index=p_index),
            user_scope_mode=row[4],
            user_scope_ids=self._load_user_scope_ids(thread_id=thread_id, p_index=p_index),
            sub_state=row[5],
            offline_state=row[6],
            is_regex=row[7],
            case_sensitive=row[8],
            color=row[9],
            disabled=row[10],
            notify=row[11],
            priority=int(row[12]),
        )

@dataclass(slots=True)
class PostgresReplyRepository(ReplyRepository):
    """Store and retrieve auto-replies attached to patterns."""

    database: PostgresDatabase

    def get_by_pattern(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, p_index, reply_message, reply_as_reply, disabled
                FROM reply
                WHERE thread_id = %s AND p_index = %s
                """,
                (thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def add_reply(
        self,
        *,
        thread_id: int,
        p_index: int,
        reply_message: str,
        reply_as_reply: bool,
    ) -> ReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO reply (thread_id, p_index, reply_message, reply_as_reply, disabled)
                VALUES (%s, %s, %s, %s, FALSE)
                ON CONFLICT (thread_id, p_index) DO NOTHING
                RETURNING thread_id, p_index, reply_message, reply_as_reply, disabled
                """,
                (thread_id, p_index, reply_message, reply_as_reply),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def remove_reply(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM reply
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, reply_message, reply_as_reply, disabled
                """,
                (thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def set_reply_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> ReplyRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = %s
                WHERE thread_id = %s AND p_index = %s
                RETURNING thread_id, p_index, reply_message, reply_as_reply, disabled
                """,
                (disabled, thread_id, p_index),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_reply_record(row)

    def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ReplyRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT thread_id, p_index, reply_message, reply_as_reply, disabled
                    FROM reply
                    WHERE thread_id = %s
                    ORDER BY p_index
                    """,
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT thread_id, p_index, reply_message, reply_as_reply, disabled
                    FROM reply
                    WHERE thread_id = %s AND disabled = FALSE
                    ORDER BY p_index
                    """,
                    (thread_id,),
                )
            rows = cursor.fetchall()
        return [self._build_reply_record(row) for row in rows]

    def disable_replies_for_thread(self, thread_id: int) -> int:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = TRUE
                WHERE thread_id = %s AND disabled = FALSE
                RETURNING p_index
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return len(rows)

    def enable_replies_for_thread(self, thread_id: int) -> int:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reply
                SET disabled = FALSE
                WHERE thread_id = %s AND disabled = TRUE
                RETURNING p_index
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return len(rows)

    @staticmethod
    def _build_reply_record(row: tuple) -> ReplyRecord:
        return ReplyRecord(
            thread_id=int(row[0]),
            p_index=int(row[1]),
            reply_message=row[2],
            reply_as_reply=row[3],
            disabled=row[4],
        )

@dataclass(slots=True)
class PostgresAdapterEventRepository(AdapterEventRepository):
    """Store and retrieve external adapter event triggers."""

    database: PostgresDatabase

    def upsert_event(
        self,
        *,
        thread_id: int,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
    ) -> AdapterEventRecord:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO adapter_event (thread_id, adapter_key, subject_type, subject_id, event_key, disabled)
                VALUES (%s, %s, %s, %s, %s, FALSE)
                ON CONFLICT (thread_id, adapter_key, subject_type, subject_id, event_key)
                DO UPDATE SET disabled = FALSE
                RETURNING event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                """,
                (thread_id, adapter_key, subject_type, subject_id, event_key),
            )
            row = cursor.fetchone()
        assert row is not None
        return self._build_record(row)

    def get_event(
        self,
        *,
        thread_id: int,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
    ) -> AdapterEventRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
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
            row = cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    def list_events_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[AdapterEventRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                    FROM adapter_event
                    WHERE thread_id = %s
                    ORDER BY adapter_key, event_key, subject_id
                    """,
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT event_id, thread_id, adapter_key, subject_type, subject_id, event_key, disabled
                    FROM adapter_event
                    WHERE thread_id = %s AND disabled = FALSE
                    ORDER BY adapter_key, event_key, subject_id
                    """,
                    (thread_id,),
                )
            rows = cursor.fetchall()
        return [self._build_record(row) for row in rows]

    def list_matching_events(
        self,
        *,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
        include_disabled: bool = False,
    ) -> list[AdapterEventRecord]:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if include_disabled:
                cursor.execute(
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
                cursor.execute(
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
            rows = cursor.fetchall()
        return [self._build_record(row) for row in rows]

    @staticmethod
    def _build_record(row: tuple) -> AdapterEventRecord:
        return AdapterEventRecord(
            event_id=int(row[0]),
            thread_id=int(row[1]),
            adapter_key=str(row[2]),
            subject_type=str(row[3]),
            subject_id=str(row[4]),
            event_key=str(row[5]),
            disabled=bool(row[6]),
        )

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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO adapter_event_action (event_id, action_type, message_template, reply_as_reply, disabled)
                VALUES (%s, %s, %s, %s, FALSE)
                ON CONFLICT (event_id, action_type)
                DO UPDATE SET
                    message_template = EXCLUDED.message_template,
                    reply_as_reply = EXCLUDED.reply_as_reply,
                    disabled = FALSE
                RETURNING event_id, action_type, message_template, reply_as_reply, disabled
                """,
                (event_id, action_type, message_template, reply_as_reply),
            )
            row = cursor.fetchone()
        assert row is not None
        return self._build_record(row)

    def get_action(self, *, event_id: int, action_type: str) -> AdapterEventActionRecord | None:
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_id, action_type, message_template, reply_as_reply, disabled
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM adapter_event_action
                WHERE event_id = %s AND action_type = %s
                RETURNING event_id, action_type, message_template, reply_as_reply, disabled
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_event_action
                SET disabled = %s
                WHERE event_id = %s AND action_type = %s
                RETURNING event_id, action_type, message_template, reply_as_reply, disabled
                """,
                (disabled, event_id, action_type),
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT event_id, action_type, message_template, reply_as_reply, disabled
                    FROM adapter_event_action
                    WHERE event_id = %s
                    ORDER BY action_type
                    """,
                    (event_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT event_id, action_type, message_template, reply_as_reply, disabled
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            if include_disabled:
                cursor.execute(
                    """
                    SELECT ae.event_id, ae.thread_id, ae.adapter_key, ae.subject_type, ae.subject_id, ae.event_key, ae.disabled,
                           aea.event_id, aea.action_type, aea.message_template, aea.reply_as_reply, aea.disabled
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
                           aea.event_id, aea.action_type, aea.message_template, aea.reply_as_reply, aea.disabled
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
            disabled=bool(row[4]),
        )

