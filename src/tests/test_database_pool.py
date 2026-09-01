from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from psycopg_pool import PoolTimeout

from src.config import AppConfig
from src.database.postgres.database import PostgresDatabase
from src.errors import DatabasePoolExhaustedError


@dataclass
class FakeCursor:
    executed: list[str]
    fetched: bool = False

    async def execute(self, query: str) -> None:
        self.executed.append(query)

    async def fetchone(self) -> tuple[int]:
        self.fetched = True
        return (1,)

    async def __aenter__(self) -> FakeCursor:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class FakeConnection:
    closed: bool = False
    commit_calls: int = 0
    rollback_calls: int = 0
    executed: list[str] | None = None

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    def cursor(self) -> FakeCursor:
        if self.executed is None:
            self.executed = []
        return FakeCursor(self.executed)


class FakePool:
    def __init__(self, *_args, **_kwargs) -> None:
        self.connection_instance = FakeConnection()
        self.open_calls = 0
        self.close_calls = 0

    async def open(self) -> None:
        self.open_calls += 1

    async def close(self) -> None:
        self.close_calls += 1

    @asynccontextmanager
    async def connection(self):
        yield self.connection_instance


class TimeoutPool(FakePool):
    @asynccontextmanager
    async def connection(self):
        raise PoolTimeout("timeout")
        yield


@pytest.mark.asyncio
async def test_database_healthcheck_uses_async_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pool = FakePool()
    monkeypatch.setattr("src.database.postgres.database.AsyncConnectionPool", lambda *_args, **_kwargs: fake_pool)
    database = PostgresDatabase(AppConfig(), max_pool_size=1, acquire_timeout_seconds=0.01)

    await database.open()
    await database.healthcheck()
    await database.close()

    assert fake_pool.open_calls == 1
    assert fake_pool.close_calls == 1
    assert fake_pool.connection_instance.executed == ["SELECT 1"]
    assert fake_pool.connection_instance.rollback_calls == 1


@pytest.mark.asyncio
async def test_database_async_connection_commits_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pool = FakePool()
    monkeypatch.setattr("src.database.postgres.database.AsyncConnectionPool", lambda *_args, **_kwargs: fake_pool)
    database = PostgresDatabase(AppConfig(), max_pool_size=1, acquire_timeout_seconds=0.01)

    await database.open()
    async with database.async_connection() as connection:
        assert connection is fake_pool.connection_instance

    assert fake_pool.connection_instance.commit_calls == 1
    assert fake_pool.connection_instance.rollback_calls == 0


@pytest.mark.asyncio
async def test_database_pool_converts_pool_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.database.postgres.database.AsyncConnectionPool", lambda *_args, **_kwargs: TimeoutPool())
    database = PostgresDatabase(AppConfig(), max_pool_size=1, acquire_timeout_seconds=0.01)

    await database.open()

    with pytest.raises(DatabasePoolExhaustedError):
        async with database.read_connection():
            pass
