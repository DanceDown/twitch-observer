from __future__ import annotations

import pytest

from src.localization import Localizer, LocalizationError


def test_localizer_interpolates_placeholders_and_supports_backslash_escaping() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer.text(
        "results.thread.language_updated.message",
        language="english",
        LANGUAGE_NAME="German",
        LANGUAGE_CODE="german",
    )
    escaped = localizer._interpolate(r"Literal \{NAME\} and \\ and {VALUE}", {"VALUE": "ok"})  # type: ignore[attr-defined]

    assert "German" in rendered
    assert "german" in rendered
    assert "{LANGUAGE_NAME}" not in rendered
    assert "{LANGUAGE_CODE}" not in rendered
    assert "{NAME}" in escaped
    assert escaped.endswith("ok")


def test_localizer_raises_for_missing_placeholder_values() -> None:
    localizer = Localizer.from_directory()

    with pytest.raises(LocalizationError):
        localizer.text("results.channel.added", language="english", DISPLAY_NAME="Example")
