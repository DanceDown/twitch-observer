"""Internal PostgreSQL repository helpers."""

from __future__ import annotations

from src.errors import RepositoryInvariantError


def require_row(row: tuple | None, *, operation: str) -> tuple:
    """Require one row from a repository query/update contract."""
    if row is None:
        raise RepositoryInvariantError(f"Repository operation `{operation}` returned no row.")
    return row


def require_value[T](value: T | None, *, operation: str) -> T:
    """Require one non-null value from a repository contract."""
    if value is None:
        raise RepositoryInvariantError(f"Repository operation `{operation}` returned no value.")
    return value
