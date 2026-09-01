from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from src.database.postgres.database import PostgresDatabase
from src.database.postgres.migrations import PostgresMigrationRunner


@dataclass
class FakeMigrationCursor:
    applied_versions: set[str]
    statements: list[tuple[str, tuple[object, ...] | None]]
    rows: list[tuple[object, ...]] = field(default_factory=list)

    async def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        self.statements.append((query, params))
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT version FROM schema_migrations"):
            self.rows = [(version,) for version in sorted(self.applied_versions)]
            return
        if normalized.startswith("INSERT INTO schema_migrations"):
            if params is not None:
                self.applied_versions.add(str(params[0]))
            self.rows = []
            return
        self.rows = []

    async def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)

    async def __aenter__(self) -> FakeMigrationCursor:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class FakeMigrationConnection:
    cursor_instance: FakeMigrationCursor

    def cursor(self) -> FakeMigrationCursor:
        return self.cursor_instance


@dataclass
class FakeMigrationDatabase:
    applied_versions: set[str] = field(default_factory=set)
    statements: list[tuple[str, tuple[object, ...] | None]] = field(default_factory=list)

    @asynccontextmanager
    async def async_cursor(self):
        yield FakeMigrationCursor(applied_versions=self.applied_versions, statements=self.statements)

    @asynccontextmanager
    async def read_cursor(self):
        yield FakeMigrationCursor(applied_versions=self.applied_versions, statements=self.statements)

    @asynccontextmanager
    async def async_connection(self):
        yield FakeMigrationConnection(
            cursor_instance=FakeMigrationCursor(applied_versions=self.applied_versions, statements=self.statements)
        )


def _postgres_database(database: FakeMigrationDatabase) -> PostgresDatabase:
    return cast(PostgresDatabase, database)


@pytest.mark.asyncio
async def test_postgres_migration_runner_applies_pending_files_in_order(tmp_path: Path) -> None:
    (tmp_path / "2026-07-01-first.sql").write_text("SELECT 'first';", encoding="utf-8")
    (tmp_path / "2026-07-02-second.sql").write_text("SELECT 'second';", encoding="utf-8")
    database = FakeMigrationDatabase()

    runner = PostgresMigrationRunner(database=_postgres_database(database), migrations_directory=tmp_path)
    await runner.apply_pending()

    assert database.applied_versions == {"2026-07-01-first.sql", "2026-07-02-second.sql"}
    queries = [query for query, _params in database.statements]
    assert any("CREATE TABLE IF NOT EXISTS schema_migrations" in query for query in queries)
    assert any("SELECT version" in query for query in queries)
    assert any("SELECT 'first';" in query for query in queries)
    assert any("SELECT 'second';" in query for query in queries)


@pytest.mark.asyncio
async def test_postgres_migration_runner_skips_already_applied_files(tmp_path: Path) -> None:
    (tmp_path / "2026-07-01-first.sql").write_text("SELECT 'first';", encoding="utf-8")
    (tmp_path / "2026-07-02-second.sql").write_text("SELECT 'second';", encoding="utf-8")
    database = FakeMigrationDatabase(applied_versions={"2026-07-01-first.sql"})

    runner = PostgresMigrationRunner(database=_postgres_database(database), migrations_directory=tmp_path)
    await runner.apply_pending()

    queries = [query for query, _params in database.statements]
    assert not any("SELECT 'first';" in query for query in queries)
    assert any("SELECT 'second';" in query for query in queries)
    assert database.applied_versions == {"2026-07-01-first.sql", "2026-07-02-second.sql"}
