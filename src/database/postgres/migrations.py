"""Ordered PostgreSQL migration runner for live schema upgrades."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .database import PostgresDatabase


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PostgresMigrationRunner:
    """Apply SQL migration files in filename order and record them once."""

    database: PostgresDatabase
    migrations_directory: Path | None = None

    def __post_init__(self) -> None:
        if self.migrations_directory is None:
            self.migrations_directory = Path(__file__).resolve().parents[1] / "migrations"

    async def apply_pending(self) -> None:
        migration_files = sorted(self._migration_files())
        if not migration_files:
            return

        await self._ensure_schema_migrations_table()
        applied_versions = await self._load_applied_versions()

        for migration_file in migration_files:
            if migration_file.name in applied_versions:
                continue
            await self._apply_one(migration_file)

    def _migration_files(self) -> list[Path]:
        directory = self.migrations_directory
        if directory is None or not directory.exists():
            return []
        return [path for path in directory.iterdir() if path.is_file() and path.suffix == ".sql"]

    async def _ensure_schema_migrations_table(self) -> None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                (),
            )

    async def _load_applied_versions(self) -> set[str]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT version
                FROM schema_migrations
                ORDER BY version
                """,
                (),
            )
            rows = await cursor.fetchall()
        return {str(row[0]) for row in rows}

    async def _apply_one(self, migration_file: Path) -> None:
        migration_sql = migration_file.read_text(encoding="utf-8").strip()
        LOGGER.info("Applying PostgreSQL migration %s", migration_file.name)
        async with self.database.async_connection() as connection:
            async with connection.cursor() as cursor:
                if migration_sql:
                    await cursor.execute(migration_sql)
                await cursor.execute(
                    """
                    INSERT INTO schema_migrations (version)
                    VALUES (%s)
                    """,
                    (migration_file.name,),
                )
        LOGGER.info("Applied PostgreSQL migration %s", migration_file.name)
