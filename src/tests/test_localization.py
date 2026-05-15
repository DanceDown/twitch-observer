from __future__ import annotations

import pytest

from src.localization import LocalizationError, Localizer, resolve_deferred_placeholders


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
    assert "{LANGUAGE_NAME}" not in rendered
    assert "{NAME}" in escaped
    assert escaped.endswith("ok")


def test_localizer_supports_deferred_user_placeholder_for_public_messages() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer._interpolate(r"\{USER\} then {USER} then {VALUE}", {"VALUE": "ok"})  # type: ignore[attr-defined]
    resolved = resolve_deferred_placeholders(rendered, USER="@Tester")

    assert resolved.startswith("{USER} then @Tester")
    assert resolved.endswith("then ok")


def test_localizer_escapes_placeholder_values_inside_inline_code_spans() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer._interpolate("Reply: `{MESSAGE}`", {"MESSAGE": "Hallo` Du`"})  # type: ignore[attr-defined]

    assert rendered == "Reply: `Hallo`\\`` Du`\\```"


def test_german_catalog_uses_utf8_umlauts() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer.text("results.command_unavailable.title", language="german")
    scope_text = localizer.text("common.scope.everyone_except", language="german", ITEMS="x")

    assert "verfügbar" in rendered
    assert "außer" in scope_text


def test_localizer_raises_for_missing_placeholder_values() -> None:
    localizer = Localizer.from_directory()

    with pytest.raises(LocalizationError):
        localizer.text("results.channel.added", language="english", DISPLAY_NAME="Example")
