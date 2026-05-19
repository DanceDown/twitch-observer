"""Shared internal exceptions for repository and invariant failures."""

from __future__ import annotations


class ApplicationInvariantError(RuntimeError):
    """Raised when internal application state violates an expected invariant."""


class RepositoryInvariantError(ApplicationInvariantError):
    """Raised when a repository cannot fulfill a write/read contract."""


class DatabasePoolExhaustedError(RuntimeError):
    """Raised when the local PostgreSQL connection pool cannot lease a connection in time."""
