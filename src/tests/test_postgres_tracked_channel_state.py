from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from src.config import AppConfig
from src.database.postgres import PostgresChannelRepository, PostgresDatabase, PostgresThreadRepository

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "database"
    / "migrations"
    / "2026-07-01-normalize_tracked_channel_state.sql"
)
EXPECTED_FIRST_CHANGE_AT = datetime.fromisoformat("2026-07-01T12:00:00+00:00")
EXPECTED_SECOND_CHANGE_AT = datetime.fromisoformat("2026-07-01T13:00:00+00:00")


def _unique_discord_channel_id() -> int:
    return 900_000_000_000 + (uuid4().int % 1_000_000_000)


async def _ensure_tracked_channel_state_table(config: AppConfig) -> None:
    async with await psycopg.AsyncConnection.connect(config.postgres_dsn) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_channel_state (
                    twitch_channel_id TEXT PRIMARY KEY,
                    is_live BOOLEAN,
                    last_live_status_at TIMESTAMPTZ
                )
                """,
                (),
            )
        await connection.commit()


async def _count_state_rows(config: AppConfig, twitch_channel_id: str) -> int:
    async with await psycopg.AsyncConnection.connect(config.postgres_dsn) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT COUNT(*) FROM tracked_channel_state WHERE twitch_channel_id = %s",
                (twitch_channel_id,),
            )
            row = await cursor.fetchone()
    return 0 if row is None else int(row[0])


async def _delete_test_rows(config: AppConfig, twitch_channel_id: str, discord_channel_ids: tuple[int, ...]) -> None:
    async with await psycopg.AsyncConnection.connect(config.postgres_dsn) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "DELETE FROM thread WHERE discord_channel_id = ANY(%s)",
                (list(discord_channel_ids),),
            )
            await cursor.execute(
                "DELETE FROM tracked_channel_state WHERE twitch_channel_id = %s",
                (twitch_channel_id,),
            )
        await connection.commit()


@pytest.mark.asyncio
async def test_postgres_channel_repository_shares_one_global_state_and_cleans_it_when_last_subscription_is_removed() -> None:
    config = AppConfig()
    await _ensure_tracked_channel_state_table(config)
    database = PostgresDatabase(config)
    await database.open()
    thread_repository = PostgresThreadRepository(database=database)
    channel_repository = PostgresChannelRepository(database=database)
    twitch_channel_id = f"tracked-state-{uuid4()}"
    discord_channel_id_1 = _unique_discord_channel_id()
    discord_channel_id_2 = _unique_discord_channel_id()

    try:
        thread_1 = await thread_repository.create(owner_id=1, discord_channel_id=discord_channel_id_1)
        thread_2 = await thread_repository.create(owner_id=2, discord_channel_id=discord_channel_id_2)

        await channel_repository.add_channel(thread_1.thread_id, twitch_channel_id)
        await channel_repository.add_channel(thread_2.thread_id, twitch_channel_id)

        assert await _count_state_rows(config, twitch_channel_id) == 1

        updated_rows = await channel_repository.set_live_state_for_twitch_channel(
            twitch_channel_id=twitch_channel_id,
            is_live=True,
            changed_at="2026-07-01T12:00:00+00:00",
        )
        first = await channel_repository.get_by_thread_and_twitch_channel(thread_1.thread_id, twitch_channel_id)
        second = await channel_repository.get_by_thread_and_twitch_channel(thread_2.thread_id, twitch_channel_id)

        assert updated_rows == 1
        assert first is not None
        assert second is not None
        assert first.is_live is True
        assert second.is_live is True
        assert first.last_live_status_at is not None
        assert second.last_live_status_at is not None
        assert datetime.fromisoformat(first.last_live_status_at).astimezone(UTC) == EXPECTED_FIRST_CHANGE_AT
        assert datetime.fromisoformat(second.last_live_status_at).astimezone(UTC) == EXPECTED_FIRST_CHANGE_AT

        await channel_repository.remove_channel(thread_1.thread_id, twitch_channel_id)
        assert await _count_state_rows(config, twitch_channel_id) == 1

        await channel_repository.remove_channel(thread_2.thread_id, twitch_channel_id)
        assert await _count_state_rows(config, twitch_channel_id) == 0
    finally:
        await _delete_test_rows(config, twitch_channel_id, (discord_channel_id_1, discord_channel_id_2))
        await database.close()


@pytest.mark.asyncio
async def test_postgres_thread_repository_delete_cleans_orphaned_global_channel_state() -> None:
    config = AppConfig()
    await _ensure_tracked_channel_state_table(config)
    database = PostgresDatabase(config)
    await database.open()
    thread_repository = PostgresThreadRepository(database=database)
    channel_repository = PostgresChannelRepository(database=database)
    twitch_channel_id = f"tracked-thread-delete-{uuid4()}"
    discord_channel_id = _unique_discord_channel_id()

    try:
        thread = await thread_repository.create(owner_id=1, discord_channel_id=discord_channel_id)
        await channel_repository.add_channel(thread.thread_id, twitch_channel_id)

        assert await _count_state_rows(config, twitch_channel_id) == 1

        deleted = await thread_repository.delete_by_discord_channel_id(discord_channel_id)

        assert deleted is not None
        assert await _count_state_rows(config, twitch_channel_id) == 0
    finally:
        await _delete_test_rows(config, twitch_channel_id, (discord_channel_id,))
        await database.close()


@pytest.mark.asyncio
async def test_tracked_channel_state_migration_backfills_newest_live_state_per_channel() -> None:
    config = AppConfig()
    await _ensure_tracked_channel_state_table(config)
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    twitch_channel_id = f"tracked-migration-{uuid4()}"
    discord_channel_id_1 = _unique_discord_channel_id()
    discord_channel_id_2 = _unique_discord_channel_id()

    async with await psycopg.AsyncConnection.connect(config.postgres_dsn) as connection:
        async with connection.cursor() as cursor:
            try:
                await cursor.execute(
                    "ALTER TABLE channel ADD COLUMN IF NOT EXISTS is_live BOOLEAN",
                    (),
                )
                await cursor.execute(
                    "ALTER TABLE channel ADD COLUMN IF NOT EXISTS last_live_status_at TIMESTAMPTZ",
                    (),
                )
                await cursor.execute(
                    """
                    INSERT INTO thread (owner_id, discord_channel_id)
                    VALUES (%s, %s), (%s, %s)
                    RETURNING thread_id
                    """,
                    (1, discord_channel_id_1, 2, discord_channel_id_2),
                )
                rows = await cursor.fetchall()
                thread_id_1 = int(rows[0][0])
                thread_id_2 = int(rows[1][0])

                await cursor.execute(
                    "DELETE FROM tracked_channel_state WHERE twitch_channel_id = %s",
                    (twitch_channel_id,),
                )
                await cursor.execute(
                    """
                    INSERT INTO channel (thread_id, twitch_channel_id, is_live, last_live_status_at)
                    VALUES
                        (%s, %s, %s, %s),
                        (%s, %s, %s, %s)
                    """,
                    (
                        thread_id_1,
                        twitch_channel_id,
                        False,
                        "2026-07-01T12:00:00+00:00",
                        thread_id_2,
                        twitch_channel_id,
                        True,
                        "2026-07-01T13:00:00+00:00",
                    ),
                )

                await cursor.execute(migration_sql)
                await cursor.execute(
                    """
                    SELECT is_live, last_live_status_at
                    FROM tracked_channel_state
                    WHERE twitch_channel_id = %s
                    """,
                    (twitch_channel_id,),
                )
                winner = await cursor.fetchone()

                assert winner is not None
                assert winner[0] is True
                assert winner[1].astimezone(UTC) == EXPECTED_SECOND_CHANGE_AT
            finally:
                await connection.rollback()
