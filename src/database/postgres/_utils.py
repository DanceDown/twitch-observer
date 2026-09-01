"""Internal PostgreSQL repository helpers."""

from __future__ import annotations

from src.errors import RepositoryInvariantError


def require_row[T: tuple[object, ...]](row: T | None, *, operation: str) -> T:
    """Require one row from a repository query/update contract."""
    if row is None:
        raise RepositoryInvariantError.operation_returned_no_row(operation)
    return row


def require_value[T](value: T | None, *, operation: str) -> T:
    """Require one non-null value from a repository contract."""
    if value is None:
        raise RepositoryInvariantError.operation_returned_no_value(operation)
    return value
