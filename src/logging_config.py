"""Logging setup helpers for compact production logs."""

from __future__ import annotations

import logging
from types import TracebackType

from src.config import AppConfig


class CompactExceptionFilter(logging.Filter):
    """Replace traceback-heavy exception logs with compact one-line summaries."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Mutate exception-bearing records so handlers do not render tracebacks."""
        if not record.exc_info:
            return True
        exc_type, error, _traceback = self._normalize_exc_info(record.exc_info)
        if error is None:
            record.exc_info = None
            record.exc_text = None
            return True
        rendered_message = record.getMessage()
        record.msg = f"{rendered_message} error_type={exc_type.__name__} error={self._compact_message(error)}"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True

    @staticmethod
    def _normalize_exc_info(
        exc_info: object,
    ) -> tuple[type[BaseException], BaseException | None, TracebackType | None]:
        if isinstance(exc_info, tuple) and len(exc_info) == 3:
            exc_type, error, traceback = exc_info
            if isinstance(exc_type, type) and issubclass(exc_type, BaseException):
                return exc_type, error if isinstance(error, BaseException) else None, traceback
        return Exception, None, None

    @staticmethod
    def _compact_message(error: BaseException) -> str:
        message = " ".join(str(error).split())
        return message or error.__class__.__name__


def configure_logging(config: AppConfig) -> None:
    """Configure application logging and suppress tracebacks unless requested."""
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    if config.log_tracebacks:
        return
    exception_filter = CompactExceptionFilter()
    for handler in logging.getLogger().handlers:
        if not any(isinstance(existing_filter, CompactExceptionFilter) for existing_filter in handler.filters):
            handler.addFilter(exception_filter)
