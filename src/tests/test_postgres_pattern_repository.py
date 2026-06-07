from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.database.records import ChatPatternSeedRecord
from src.database.postgres import PostgresPatternRepository


@dataclass
class RecordingCursor:
    statements: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    rows: list[tuple[object, ...]] = field(default_factory=list)

    async def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.statements.append((query, params))

    async def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


@dataclass
class RecordingDatabase:
    cursor_instance: RecordingCursor = field(default_factory=RecordingCursor)

    @asynccontextmanager
    async def read_cursor(self) -> RecordingCursor:
        yield self.cursor_instance


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
    repository = PostgresPatternRepository(database=database)  # type: ignore[arg-type]

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
    _query, params = database.cursor_instance.statements[0]
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
    repository = PostgresPatternRepository(database=database)  # type: ignore[arg-type]

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
    assert "WITH matched" in query
    assert params == (0, 7, 3, True, "42")
