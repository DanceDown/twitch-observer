from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.config import AppConfig
from src.database.postgres.database import PostgresDatabase
from src.errors import DatabasePoolExhaustedError


@dataclass
class FakeConnection:
    closed: bool = False
    commit_calls: int = 0
    rollback_calls: int = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.closed = True


def test_database_pool_enforces_hard_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    connections: list[FakeConnection] = []

    def fake_connect(dsn: str) -> FakeConnection:
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("src.database.postgres.database.psycopg.connect", fake_connect)
    database = PostgresDatabase(
        AppConfig(),
        max_pool_size=1,
        acquire_timeout_seconds=0.01,
    )

    with database.connection():
        with pytest.raises(DatabasePoolExhaustedError):
            with database.connection():
                pass

    assert len(connections) == 1


def test_database_pool_reuses_released_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    connections: list[FakeConnection] = []

    def fake_connect(dsn: str) -> FakeConnection:
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("src.database.postgres.database.psycopg.connect", fake_connect)
    database = PostgresDatabase(
        AppConfig(),
        max_pool_size=1,
        acquire_timeout_seconds=0.01,
    )

    with database.connection() as first:
        assert first is connections[0]

    with database.connection() as second:
        assert second is connections[0]

    assert len(connections) == 1
