from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import psycopg
import pytest

from src.database.postgres import PostgresPatternRepository
from src.database.postgres.database import PostgresDatabase
from src.database.records import ChatPatternSeedRecord, PatternCreate, PatternDefinition


@dataclass
class RecordingCursor:
    statements: list[tuple[object, tuple[object, ...]]] = field(default_factory=list)
    rows: list[tuple[object, ...]] = field(default_factory=list)

    async def execute(self, query: object, params: tuple[object, ...]) -> None:
        self.statements.append((query, params))

    async def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


@dataclass
class RecordingDatabase:
    cursor_instance: RecordingCursor = field(default_factory=RecordingCursor)

    @asynccontextmanager
    async def read_cursor(self) -> RecordingCursor:
        yield self.cursor_instance


class FakePatternSequenceUniqueViolation(psycopg.errors.UniqueViolation):
    @property
    def diag(self) -> object:
        return SimpleNamespace(constraint_name="pattern_pkey")


@dataclass
class TransactionCursor:
    statements: list[tuple[object, tuple[object, ...]]] = field(default_factory=list)
    rows: list[tuple[object, ...]] = field(default_factory=list)
    fail_on_first_execute: bool = False
    _execute_calls: int = 0

    async def execute(self, query: object, params: tuple[object, ...]) -> None:
        self.statements.append((query, params))
        self._execute_calls += 1
        if self.fail_on_first_execute and self._execute_calls == 1:
            raise FakePatternSequenceUniqueViolation("duplicate key value violates unique constraint pattern_pkey")

    async def executemany(self, query: object, params_seq: list[tuple[object, ...]]) -> None:
        self.statements.append((query, tuple(params_seq)))

    async def fetchone(self) -> tuple[object, ...] | None:
        return self.rows.pop(0) if self.rows else None


@dataclass
class RecordingConnection:
    cursor_instance: TransactionCursor

    @asynccontextmanager
    async def cursor(self) -> TransactionCursor:
        yield self.cursor_instance


@dataclass
class RecordingWriteDatabase:
    transaction_cursors: list[TransactionCursor]
    reset_cursor: RecordingCursor = field(default_factory=RecordingCursor)
    _transaction_index: int = 0

    @asynccontextmanager
    async def async_transaction(self) -> RecordingConnection:
        connection = RecordingConnection(cursor_instance=self.transaction_cursors[self._transaction_index])
        self._transaction_index += 1
        yield connection

    @asynccontextmanager
    async def async_cursor(self) -> RecordingCursor:
        yield self.reset_cursor


def _postgres_database(database: RecordingDatabase | RecordingWriteDatabase) -> PostgresDatabase:
    return cast(PostgresDatabase, database)


def _query_text(query: object) -> str:
    return query if isinstance(query, str) else str(query)


@pytest.mark.asyncio
async def test_postgres_pattern_repository_maps_chat_match_seeds() -> None:
    database = RecordingDatabase(
        cursor_instance=RecordingCursor(
            rows=[
                (
                    7,
                    3,
                    "hello",
                    False,
                    True,
                    9,
                    True,
                )
            ]
        )
    )
    repository = PostgresPatternRepository(database=_postgres_database(database))

    rows = await repository.list_chat_match_seeds(
        broadcaster_id="42",
        author_id="7",
        sender_is_sub=True,
    )

    assert len(rows) == 1
    seed = rows[0]
    assert seed.thread_id == 7
    assert seed.pattern_id == 3
    assert seed.regex == "hello"
    assert seed.is_regex is False
    assert seed.case_sensitive is True
    assert seed.priority == 9
    assert seed.explicit_user_scope_match is True

    assert len(database.cursor_instance.statements) == 1
    query, params = database.cursor_instance.statements[0]
    query_text = _query_text(query)
    assert "tracked_channel_state" in query_text
    assert params == ("42", "7", "7", "42", True, True)


@pytest.mark.asyncio
async def test_postgres_pattern_repository_hydrates_chat_match_candidates() -> None:
    changed_at = datetime.now(UTC)
    database = RecordingDatabase(
        cursor_instance=RecordingCursor(
            rows=[
                (
                    True,
                    7,
                    200,
                    1000,
                    "german",
                    True,
                    "#112233",
                    55,
                    7,
                    "42",
                    "#abcdef",
                    True,
                    changed_at,
                    7,
                    3,
                    "hello",
                    "only_selected",
                    "only_selected",
                    "subs",
                    "online",
                    False,
                    True,
                    "#123456",
                    False,
                    9,
                    7,
                    3,
                    "pong",
                    True,
                    False,
                )
            ]
        )
    )
    repository = PostgresPatternRepository(database=_postgres_database(database))

    rows = await repository.hydrate_chat_match_candidates(
        broadcaster_id="42",
        seeds=(
            ChatPatternSeedRecord(
                thread_id=7,
                pattern_id=3,
                regex="hello",
                is_regex=False,
                case_sensitive=True,
                priority=9,
                explicit_user_scope_match=True,
            ),
        ),
    )

    assert len(rows) == 1
    candidate = rows[0]
    assert candidate.thread.thread_id == 7
    assert candidate.thread.enabled is True
    assert candidate.source_channel.twitch_channel_id == "42"
    assert candidate.source_channel.last_live_status_at == changed_at.isoformat()
    assert candidate.pattern.pattern_id == 3
    assert candidate.pattern.priority == 9
    assert candidate.pattern.channel_scope_ids == ()
    assert candidate.reply is not None
    assert candidate.reply.reply_message == "pong"
    assert candidate.explicit_user_scope_match is True

    assert len(database.cursor_instance.statements) == 1
    query, params = database.cursor_instance.statements[0]
    query_text = _query_text(query)
    assert "WITH matched" in query_text
    assert "tracked_channel_state" in query_text
    assert params == (0, 7, 3, True, "42")


@pytest.mark.asyncio
async def test_postgres_pattern_repository_repairs_desynced_pattern_sequence_and_retries_insert() -> None:
    first_insert_cursor = TransactionCursor(fail_on_first_execute=True)
    second_insert_cursor = TransactionCursor(
        rows=[
            (
                7,
                26,
                "hello",
                "all_tracked",
                "all_users",
                "all",
                "both",
                False,
                False,
                None,
                False,
                0,
            )
        ]
    )
    database = RecordingWriteDatabase(transaction_cursors=[first_insert_cursor, second_insert_cursor])
    repository = PostgresPatternRepository(database=_postgres_database(database))

    pattern = await repository.add_pattern(
        PatternCreate(
            thread_id=7,
            definition=PatternDefinition(
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
            ),
            color=None,
            disabled=False,
            priority=0,
        )
    )

    assert pattern.pattern_id == 26
    assert len(first_insert_cursor.statements) == 1
    assert len(second_insert_cursor.statements) == 1
    assert len(database.reset_cursor.statements) == 1
    reset_query, reset_params = database.reset_cursor.statements[0]
    reset_query_text = _query_text(reset_query)
    assert "pg_get_serial_sequence('pattern', 'pattern_id')" in reset_query_text
    assert "SELECT MAX(pattern_id) FROM pattern" in reset_query_text
    assert reset_params == ()
