"""PostgreSQL connection pooling helpers."""

from __future__ import annotations

from collections import deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import asyncio
from threading import Condition, Lock
from time import monotonic
from typing import AsyncIterator, Iterator

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
    _idle_async_connections: deque[psycopg.AsyncConnection] = field(default_factory=deque, init=False)
    _async_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _async_condition: asyncio.Condition = field(init=False)
    _async_allocated: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.max_pool_size is None:
            self.max_pool_size = max(1, self.config.postgres_pool_size)
        if self.acquire_timeout_seconds is None:
            self.acquire_timeout_seconds = max(0.0, self.config.postgres_pool_acquire_timeout_seconds)
        self._condition = Condition(self._lock)
        self._async_condition = asyncio.Condition(self._async_lock)

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

    @asynccontextmanager
    async def read_connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        """Lease one async connection for one read-only repository operation."""
        connection = await self._acquire_async()
        try:
            yield connection
            if not connection.closed:
                await connection.rollback()
        finally:
            await self._release_async(connection)

    @asynccontextmanager
    async def read_cursor(self) -> AsyncIterator[psycopg.AsyncCursor]:
        """Lease one async cursor for one read-only repository operation."""
        async with self.read_connection() as connection:
            async with connection.cursor() as cursor:
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

    async def close_async(self) -> None:
        """Close all idle async connections in the local pool."""
        async with self._async_condition:
            while self._idle_async_connections:
                connection = self._idle_async_connections.popleft()
                if not connection.closed:
                    await connection.close()
            self._async_allocated = 0
            self._async_condition.notify_all()

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

    async def _acquire_async(self) -> psycopg.AsyncConnection:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (self.acquire_timeout_seconds or 0.0)
        async with self._async_condition:
            while True:
                while self._idle_async_connections:
                    connection = self._idle_async_connections.popleft()
                    if not connection.closed:
                        return connection
                    self._async_allocated = max(0, self._async_allocated - 1)

                if self._async_allocated < self.max_pool_size:
                    self._async_allocated += 1
                    break

                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise DatabasePoolExhaustedError(
                        f"PostgreSQL async read pool exhausted after waiting {self.acquire_timeout_seconds:.2f}s "
                        f"(pool_size={self.max_pool_size})."
                    )
                try:
                    await asyncio.wait_for(self._async_condition.wait(), timeout=remaining)
                except TimeoutError as error:
                    raise DatabasePoolExhaustedError(
                        f"PostgreSQL async read pool exhausted after waiting {self.acquire_timeout_seconds:.2f}s "
                        f"(pool_size={self.max_pool_size})."
                    ) from error

        try:
            connection = await psycopg.AsyncConnection.connect(self.config.postgres_dsn, autocommit=True)
            return connection
        except Exception:
            async with self._async_condition:
                self._async_allocated = max(0, self._async_allocated - 1)
                self._async_condition.notify()
            raise

    async def _release_async(self, connection: psycopg.AsyncConnection) -> None:
        if connection.closed:
            async with self._async_condition:
                self._async_allocated = max(0, self._async_allocated - 1)
                self._async_condition.notify()
            return
        try:
            await connection.rollback()
        except Exception:
            await connection.close()
            async with self._async_condition:
                self._async_allocated = max(0, self._async_allocated - 1)
                self._async_condition.notify()
            return

        async with self._async_condition:
            if len(self._idle_async_connections) >= self.max_pool_size:
                await connection.close()
                self._async_allocated = max(0, self._async_allocated - 1)
                self._async_condition.notify()
                return
            self._idle_async_connections.append(connection)
            self._async_condition.notify()
