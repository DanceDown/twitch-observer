"""Shared internal exceptions for repository and invariant failures."""

from __future__ import annotations


class ApplicationInvariantError(RuntimeError):
    """Raised when internal application state violates an expected invariant."""

    @classmethod
    def operation_returned_no_row(cls, operation: str) -> ApplicationInvariantError:
        """Build a standard invariant error for write operations that should update one row."""
        return cls(f"{operation} returned no row.")


class InputNormalizationError(ValueError):
    """Raised when user or external input cannot be normalized safely."""

    @classmethod
    def missing_twitch_login(cls) -> InputNormalizationError:
        """Build an error for empty Twitch login values."""
        return cls("Missing Twitch login.")

    @classmethod
    def missing_twitch_user_id(cls) -> InputNormalizationError:
        """Build an error for empty Twitch user ID values."""
        return cls("Missing Twitch user ID.")

    @classmethod
    def missing_discord_channel_id(cls) -> InputNormalizationError:
        """Build an error for missing Discord channel IDs."""
        return cls("Missing Discord channel ID.")

    @classmethod
    def missing_language(cls) -> InputNormalizationError:
        """Build an error for empty language values."""
        return cls("Missing language.")

    @classmethod
    def invalid_hex_color(cls) -> InputNormalizationError:
        """Build an error for malformed Discord embed colors."""
        return cls("Color must use #RRGGBB.")

    @classmethod
    def empty_text_field(cls, field_name: str) -> InputNormalizationError:
        """Build an error for required free-text fields after trimming."""
        return cls(f"{field_name} must not be empty.")

    @classmethod
    def text_field_too_long(cls, field_name: str) -> InputNormalizationError:
        """Build an error for free-text fields above their configured limit."""
        return cls(f"{field_name} is too long.")


class MissingTwitchMessageIdError(ValueError):
    """Raised when persistence needs a Twitch message ID but IRC did not provide one."""

    def __init__(self) -> None:
        """Create the missing-message-ID error with a stable message."""
        super().__init__("Twitch IRC message is missing message_id.")


class RepositoryInvariantError(ApplicationInvariantError):
    """Raised when a repository cannot fulfill a write/read contract."""

    @classmethod
    def operation_returned_no_row(cls, operation: str) -> RepositoryInvariantError:
        """Build a standard repository error for queries that must return one row."""
        return cls(f"Repository operation `{operation}` returned no row.")

    @classmethod
    def operation_returned_no_value(cls, operation: str) -> RepositoryInvariantError:
        """Build a standard repository error for queries that must return one scalar value."""
        return cls(f"Repository operation `{operation}` returned no value.")


class DatabaseNotOpenError(RuntimeError):
    """Raised when repository code tries to use PostgreSQL before startup completed."""

    def __init__(self) -> None:
        """Create the unopened-database error with a stable message."""
        super().__init__("PostgresDatabase.open() must be awaited before using the pool.")


class DatabasePoolExhaustedError(RuntimeError):
    """Raised when the local PostgreSQL connection pool cannot lease a connection in time."""

    @classmethod
    def from_pool_settings(
        cls,
        *,
        acquire_timeout_seconds: float | None,
        max_pool_size: int | None,
    ) -> DatabasePoolExhaustedError:
        """Build a pool exhaustion error with the configured wait time and pool size."""
        return cls(f"PostgreSQL pool exhausted after waiting {acquire_timeout_seconds:.2f}s (pool_size={max_pool_size}).")
