from __future__ import annotations

import logging

from src.logging_config import CompactExceptionFilter


def test_compact_exception_filter_replaces_traceback_with_error_summary() -> None:
    error = ValueError("broken\nnetwork")
    record = logging.LogRecord(
        name="discord.client",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Attempting a reconnect in %.2fs",
        args=(1.25,),
        exc_info=(type(error), error, error.__traceback__),
        func=None,
        sinfo=None,
    )

    assert CompactExceptionFilter().filter(record) is True

    assert record.exc_info is None
    assert record.exc_text is None
    assert record.args == ()
    assert record.getMessage() == "Attempting a reconnect in 1.25s error_type=ValueError error=broken network"
