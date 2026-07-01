"""PostgreSQL repository for message-driven patterns."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import psycopg

from ..records import ChatPatternCandidateRecord, ChatPatternSeedRecord, ChannelRecord, PatternRecord, ReplyRecord, ThreadRecord
from ..repositories import PatternRepository
from ._utils import require_row
from .database import PostgresDatabase


PatternRow = tuple
PatternSeedRow = tuple
HydratedCandidateRow = tuple


@dataclass(slots=True)
class PostgresPatternRepository(PatternRepository):
    """Store and retrieve ping/regex rules."""

    database: PostgresDatabase
    _PATTERN_SEQUENCE_CONSTRAINT_NAMES = frozenset({"pattern_pkey", "uniq_pattern_thread_internal_id"})

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
                       priority
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
        row = await self._insert_pattern_with_retry(
            thread_id=thread_id,
            regex=regex,
            channel_scope_mode=channel_scope_mode,
            channel_scope_ids=channel_scope_ids,
            user_scope_mode=user_scope_mode,
            user_scope_ids=user_scope_ids,
            sub_state=sub_state,
            offline_state=offline_state,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            color=color,
            disabled=disabled,
            priority=priority,
        )
        return self._build_pattern_record(
            row,
            channel_scope_ids=tuple(sorted(channel_scope_ids)),
            user_scope_ids=tuple(sorted(user_scope_ids)),
        )

    async def _insert_pattern_with_retry(
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
    ) -> PatternRow:
        for attempt in range(2):
            try:
                return await self._insert_pattern_once(
                    thread_id=thread_id,
                    regex=regex,
                    channel_scope_mode=channel_scope_mode,
                    channel_scope_ids=channel_scope_ids,
                    user_scope_mode=user_scope_mode,
                    user_scope_ids=user_scope_ids,
                    sub_state=sub_state,
                    offline_state=offline_state,
                    is_regex=is_regex,
                    case_sensitive=case_sensitive,
                    color=color,
                    disabled=disabled,
                    priority=priority,
                )
            except psycopg.errors.UniqueViolation as error:
                if attempt > 0 or not self._is_pattern_sequence_conflict(error):
                    raise
                await self._reset_pattern_id_sequence()
        raise RuntimeError("Pattern insert retry exhausted unexpectedly.")

    async def _insert_pattern_once(
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
    ) -> PatternRow:
        async with self.database.async_transaction() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO pattern (
                        thread_id, regex, channel_scope_mode, user_scope_mode,
                        sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                        priority
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING thread_id, pattern_id, regex, channel_scope_mode, user_scope_mode,
                              sub_state, offline_state, is_regex, case_sensitive, color, disabled,
                              priority
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
        return row

    async def _reset_pattern_id_sequence(self) -> None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('pattern', 'pattern_id'),
                    COALESCE((SELECT MAX(pattern_id) FROM pattern), 0) + 1,
                    FALSE
                )
                """,
                (),
            )

    @classmethod
    def _is_pattern_sequence_conflict(cls, error: psycopg.errors.UniqueViolation) -> bool:
        constraint_name = getattr(getattr(error, "diag", None), "constraint_name", None)
        return constraint_name in cls._PATTERN_SEQUENCE_CONSTRAINT_NAMES

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
                          priority
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
                          priority
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
                          priority
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
                       priority
                FROM pattern
                WHERE thread_id = %s AND disabled = FALSE
                ORDER BY priority DESC, pattern_id
                """,
                (thread_id,),
            )
            rows = await cursor.fetchall()
        return await self._build_patterns_from_rows(rows)

    async def list_chat_match_seeds(
        self,
        *,
        broadcaster_id: str,
        author_id: str,
        sender_is_sub: bool,
    ) -> list[ChatPatternSeedRecord]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    p.thread_id,
                    p.pattern_id,
                    p.regex,
                    p.is_regex,
                    p.case_sensitive,
                    p.priority,
                    CASE
                        WHEN p.user_scope_mode = 'only_selected' AND pus_selected.pattern_id IS NOT NULL THEN TRUE
                        ELSE FALSE
                    END AS explicit_user_scope_match
                FROM channel AS c
                LEFT JOIN tracked_channel_state AS tcs
                  ON tcs.twitch_channel_id = c.twitch_channel_id
                JOIN thread AS t
                  ON t.thread_id = c.thread_id
                JOIN pattern AS p
                  ON p.thread_id = c.thread_id
                LEFT JOIN pattern_channel_scope AS pcs_selected
                  ON pcs_selected.thread_id = p.thread_id
                 AND pcs_selected.pattern_id = p.pattern_id
                 AND pcs_selected.twitch_channel_id = %s
                LEFT JOIN pattern_user_scope AS pus_selected
                  ON pus_selected.thread_id = p.thread_id
                 AND pus_selected.pattern_id = p.pattern_id
                 AND pus_selected.twitch_user_id = %s
                LEFT JOIN tracked_user AS tu
                  ON tu.thread_id = p.thread_id
                 AND tu.twitch_user_id = %s
                WHERE c.twitch_channel_id = %s
                  AND t.enabled = TRUE
                  AND p.disabled = FALSE
                  AND (
                      p.channel_scope_mode = 'all_tracked'
                      OR (
                          p.channel_scope_mode = 'only_selected'
                          AND pcs_selected.pattern_id IS NOT NULL
                      )
                      OR (
                          p.channel_scope_mode = 'all_except_selected'
                          AND pcs_selected.pattern_id IS NULL
                      )
                  )
                  AND (
                      p.user_scope_mode = 'all_users'
                      OR (
                          p.user_scope_mode = 'only_selected'
                          AND pus_selected.pattern_id IS NOT NULL
                      )
                      OR (
                          p.user_scope_mode = 'all_except_selected'
                          AND pus_selected.pattern_id IS NULL
                      )
                      OR (
                          p.user_scope_mode = 'all_tracked'
                          AND tu.thread_id IS NOT NULL
                      )
                      OR (
                          p.user_scope_mode = 'all_tracked_except_selected'
                          AND tu.thread_id IS NOT NULL
                          AND pus_selected.pattern_id IS NULL
                      )
                  )
                  AND (
                      p.sub_state = 'all'
                      OR (p.sub_state = 'subs' AND %s = TRUE)
                      OR (p.sub_state = 'non_subs' AND %s = FALSE)
                  )
                  AND (
                      p.offline_state = 'both'
                      OR tcs.is_live IS NULL
                      OR (p.offline_state = 'online' AND tcs.is_live = TRUE)
                      OR (p.offline_state = 'offline' AND tcs.is_live = FALSE)
                  )
                ORDER BY t.thread_id, p.priority DESC, p.pattern_id
                """,
                (
                    broadcaster_id,
                    author_id,
                    author_id,
                    broadcaster_id,
                    sender_is_sub,
                    sender_is_sub,
                ),
            )
            rows = await cursor.fetchall()
        return [self._build_chat_match_seed_record(row) for row in rows]

    async def hydrate_chat_match_candidates(
        self,
        *,
        broadcaster_id: str,
        seeds: tuple[ChatPatternSeedRecord, ...],
    ) -> list[ChatPatternCandidateRecord]:
        if not seeds:
            return []
        value_placeholders = ", ".join(["(%s, %s, %s, %s)"] * len(seeds))
        params: list[object] = []
        for index, seed in enumerate(seeds):
            params.extend((index, seed.thread_id, seed.pattern_id, seed.explicit_user_scope_match))
        params.append(broadcaster_id)
        query = f"""
                WITH matched(seed_order, thread_id, pattern_id, explicit_user_scope_match) AS (
                    VALUES {value_placeholders}
                )
                SELECT
                    m.explicit_user_scope_match,
                    t.thread_id, t.owner_id, t.discord_channel_id, t.language, t.enabled, t.color, t.account_id,
                    c.thread_id, c.twitch_channel_id, c.color, tcs.is_live, tcs.last_live_status_at,
                    p.thread_id, p.pattern_id, p.regex, p.channel_scope_mode, p.user_scope_mode,
                    p.sub_state, p.offline_state, p.is_regex, p.case_sensitive, p.color, p.disabled, p.priority,
                    r.thread_id, r.pattern_id, r.reply_message, r.reply_as_reply, r.disabled
                FROM matched AS m
                JOIN pattern AS p
                  ON p.thread_id = m.thread_id
                 AND p.pattern_id = m.pattern_id
                JOIN thread AS t
                  ON t.thread_id = p.thread_id
                JOIN channel AS c
                  ON c.thread_id = p.thread_id
                 AND c.twitch_channel_id = %s
                LEFT JOIN tracked_channel_state AS tcs
                  ON tcs.twitch_channel_id = c.twitch_channel_id
                LEFT JOIN reply AS r
                  ON r.thread_id = p.thread_id
                 AND r.pattern_id = p.pattern_id
                 AND r.disabled = FALSE
                ORDER BY m.seed_order
                """
        async with self.database.read_cursor() as cursor:
            await cursor.execute(query, tuple(params))
            rows = await cursor.fetchall()
        return [self._build_chat_match_candidate_record(row) for row in rows]

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
                       priority
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
                           priority
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
                           priority
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
            priority=int(row[11]),
        )

    @staticmethod
    def _build_chat_match_seed_record(row: PatternSeedRow) -> ChatPatternSeedRecord:
        return ChatPatternSeedRecord(
            thread_id=int(row[0]),
            pattern_id=int(row[1]),
            regex=row[2],
            is_regex=row[3],
            case_sensitive=row[4],
            priority=int(row[5]),
            explicit_user_scope_match=bool(row[6]),
        )

    @staticmethod
    def _build_chat_match_candidate_record(row: HydratedCandidateRow) -> ChatPatternCandidateRecord:
        thread = ThreadRecord(
            thread_id=int(row[1]),
            owner_id=int(row[2]),
            discord_channel_id=int(row[3]),
            language=row[4],
            enabled=row[5],
            color=row[6],
            account_id=row[7],
        )
        source_channel = ChannelRecord(
            thread_id=int(row[8]),
            twitch_channel_id=str(row[9]),
            color=row[10],
            is_live=row[11],
            last_live_status_at=(row[12].isoformat() if row[12] is not None else None),
        )
        pattern = PatternRecord(
            thread_id=int(row[13]),
            pattern_id=int(row[14]),
            regex=row[15],
            channel_scope_mode=row[16],
            channel_scope_ids=(),
            user_scope_mode=row[17],
            user_scope_ids=(),
            sub_state=row[18],
            offline_state=row[19],
            is_regex=row[20],
            case_sensitive=row[21],
            color=row[22],
            disabled=row[23],
            priority=int(row[24]),
        )
        reply = (
            None
            if row[25] is None
            else ReplyRecord(
                thread_id=int(row[25]),
                pattern_id=int(row[26]),
                reply_message=row[27],
                reply_as_reply=row[28],
                disabled=row[29],
            )
        )
        return ChatPatternCandidateRecord(
            thread=thread,
            source_channel=source_channel,
            pattern=pattern,
            reply=reply,
            explicit_user_scope_match=bool(row[0]),
        )
