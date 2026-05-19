"""PostgreSQL connection pooling helpers."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Condition, Lock
from time import monotonic
from typing import Iterator

import psycopg

from src.config import AppConfig
from src.errors import DatabasePoolExhaustedError


@dataclass(slots=True)
class PostgresDatabase:
    """Small synchronous connection pool for repository operations."""

    config: AppConfig
    max_pool_size: int | None = None
    acquire_timeout_seconds: float | None = None
    _idle_connections: deque[psycopg.Connection] = field(default_factory=deque, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)
    _condition: Condition = field(init=False)
    _allocated: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.max_pool_size is None:
            self.max_pool_size = max(1, self.config.postgres_pool_size)
        if self.acquire_timeout_seconds is None:
            self.acquire_timeout_seconds = max(0.0, self.config.postgres_pool_acquire_timeout_seconds)
        self._condition = Condition(self._lock)

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """Lease one connection for one repository operation."""
        connection = self._acquire()
        try:
            yield connection
            if not connection.closed:
                connection.commit()
        except Exception:
            if not connection.closed:
                connection.rollback()
            raise
        finally:
            self._release(connection)

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """Lease one connection for one explicit transactional operation."""
        with self.connection() as connection:
            yield connection

    @contextmanager
    def cursor(self) -> Iterator[psycopg.Cursor]:
        """Lease one cursor for one repository operation."""
        with self.connection() as connection:
            with connection.cursor() as cursor:
                yield cursor

    def close(self) -> None:
        """Close all idle connections in the local pool."""
        with self._condition:
            while self._idle_connections:
                connection = self._idle_connections.popleft()
                if not connection.closed:
                    connection.close()
            self._allocated = 0
            self._condition.notify_all()

    def healthcheck(self) -> None:
        """Validate that PostgreSQL is reachable."""
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

    def _acquire(self) -> psycopg.Connection:
        deadline = monotonic() + (self.acquire_timeout_seconds or 0.0)
        with self._condition:
            while True:
                while self._idle_connections:
                    connection = self._idle_connections.popleft()
                    if not connection.closed:
                        return connection
                    self._allocated = max(0, self._allocated - 1)

                if self._allocated < self.max_pool_size:
                    self._allocated += 1
                    break

                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise DatabasePoolExhaustedError(
                        f"PostgreSQL pool exhausted after waiting {self.acquire_timeout_seconds:.2f}s (pool_size={self.max_pool_size})."
                    )
                self._condition.wait(timeout=remaining)

        try:
            return psycopg.connect(self.config.postgres_dsn)
        except Exception:
            with self._condition:
                self._allocated = max(0, self._allocated - 1)
                self._condition.notify()
            raise

    def _release(self, connection: psycopg.Connection) -> None:
        if connection.closed:
            with self._condition:
                self._allocated = max(0, self._allocated - 1)
                self._condition.notify()
            return
        try:
            connection.rollback()
        except Exception:
            connection.close()
            with self._condition:
                self._allocated = max(0, self._allocated - 1)
                self._condition.notify()
            return

        with self._condition:
            if len(self._idle_connections) >= self.max_pool_size:
                connection.close()
                self._allocated = max(0, self._allocated - 1)
                self._condition.notify()
                return
            self._idle_connections.append(connection)
            self._condition.notify()
