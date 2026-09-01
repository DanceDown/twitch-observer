from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast

import pytest

from src.database.postgres import PostgresReplyRepository
from src.database.postgres.database import PostgresDatabase


@dataclass
class RecordingAsyncCursor:
    rows: list[tuple[int]]
    statements: list[tuple[object, tuple[object, ...]]] = field(default_factory=list)

    async def execute(self, query: object, params: tuple[object, ...]) -> None:
        self.statements.append((query, params))

    async def fetchall(self) -> list[tuple[int]]:
        return list(self.rows)


@dataclass
class RecordingWriteDatabase:
    cursor: RecordingAsyncCursor

    @asynccontextmanager
    async def async_cursor(self) -> RecordingAsyncCursor:
        yield self.cursor


def _postgres_database(database: RecordingWriteDatabase) -> PostgresDatabase:
    return cast(PostgresDatabase, database)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    [
        "disable_replies_for_thread",
        "enable_replies_for_thread",
    ],
)
async def test_bulk_reply_toggle_awaits_fetchall_and_returns_changed_count(method_name: str) -> None:
    cursor = RecordingAsyncCursor(rows=[(1,), (2,)])
    repository = PostgresReplyRepository(database=_postgres_database(RecordingWriteDatabase(cursor=cursor)))

    changed_count = await getattr(repository, method_name)(7)

    assert changed_count == 2
    assert cursor.statements[0][1] == (7,)
