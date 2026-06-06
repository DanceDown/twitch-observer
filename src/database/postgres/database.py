"""PostgreSQL async connection pooling helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

import psycopg
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from src.config import AppConfig
from src.errors import DatabasePoolExhaustedError


@dataclass(slots=True)
class PostgresDatabase:
    """Async PostgreSQL connection pool wrapper for repository operations."""

    config: AppConfig
    max_pool_size: int | None = None
    acquire_timeout_seconds: float | None = None
    _pool: AsyncConnectionPool[psycopg.AsyncConnection] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_pool_size is None:
            self.max_pool_size = max(1, self.config.postgres_pool_size)
        if self.acquire_timeout_seconds is None:
            self.acquire_timeout_seconds = max(0.0, self.config.postgres_pool_acquire_timeout_seconds)

    async def open(self) -> None:
        """Open the shared async pool once during startup."""
        if self._pool is not None:
            return
        pool = AsyncConnectionPool(
            conninfo=self.config.postgres_dsn,
            min_size=0,
            max_size=self.max_pool_size,
            timeout=self.acquire_timeout_seconds,
            open=False,
        )
        try:
            await pool.open()
        except Exception:
            await pool.close()
            raise
        self._pool = pool

    async def close(self) -> None:
        """Close the async pool during shutdown."""
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    async def healthcheck(self) -> None:
        """Validate that PostgreSQL is reachable."""
        async with self.read_cursor() as cursor:
            await cursor.execute("SELECT 1")
            await cursor.fetchone()

    @asynccontextmanager
    async def read_connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        """Lease one async connection for one read-only repository operation."""
        async with self._pool_connection() as connection:
            try:
                yield connection
            finally:
                if not connection.closed:
                    await connection.rollback()

    @asynccontextmanager
    async def read_cursor(self) -> AsyncIterator[psycopg.AsyncCursor]:
        """Lease one async cursor for one read-only repository operation."""
        async with self.read_connection() as connection:
            async with connection.cursor() as cursor:
                yield cursor

    @asynccontextmanager
    async def async_connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        """Lease one async connection for one repository operation with commit handling."""
        async with self._pool_connection() as connection:
            try:
                yield connection
                if not connection.closed:
                    await connection.commit()
            except Exception:
                if not connection.closed:
                    await connection.rollback()
                raise

    @asynccontextmanager
    async def async_transaction(self) -> AsyncIterator[psycopg.AsyncConnection]:
        """Lease one async connection for one explicit transactional operation."""
        async with self.async_connection() as connection:
            yield connection

    @asynccontextmanager
    async def async_cursor(self) -> AsyncIterator[psycopg.AsyncCursor]:
        """Lease one async cursor for one repository operation."""
        async with self.async_connection() as connection:
            async with connection.cursor() as cursor:
                yield cursor

    @asynccontextmanager
    async def _pool_connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        pool = self._pool
        if pool is None:
            raise RuntimeError("PostgresDatabase.open() must be awaited before using the pool.")
        try:
            async with pool.connection() as connection:
                yield connection
        except PoolTimeout as error:
            raise DatabasePoolExhaustedError(
                f"PostgreSQL pool exhausted after waiting {self.acquire_timeout_seconds:.2f}s (pool_size={self.max_pool_size})."
            ) from error
