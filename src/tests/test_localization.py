from __future__ import annotations

import pytest

from src.discord_results import build_result
from src.localization import LocalizationError, Localizer


def test_localizer_interpolates_placeholders_and_supports_backslash_escaping() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer.text(
        "results.thread.language_updated.body",
        language="english",
        USER="<@123456789012345678>",
        LANGUAGE_NAME="German",
    )
    escaped = localizer._interpolate(r"Literal \{NAME\} and \\ and {VALUE}", {"VALUE": "ok"})  # type: ignore[attr-defined]

    assert "German" in rendered
    assert "{LANGUAGE_NAME}" not in rendered
    assert "{NAME}" in escaped
    assert escaped.endswith("ok")


def test_localizer_replaces_user_placeholder_directly() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer._interpolate(  # type: ignore[attr-defined]
        r"\{USER\} then {RAW:USER} then {VALUE}",
        {"USER": "<@123456789012345678>", "VALUE": "ok"},
    )

    assert rendered.startswith("{USER} then <@123456789012345678>")
    assert rendered.endswith("then ok")


def test_localizer_supports_explicit_placeholder_modes() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer._interpolate(  # type: ignore[attr-defined]
        "Escaped={VALUE} Raw={RAW:VALUE} Code=`{CODE:VALUE}`",
        {"VALUE": "Hello` @everyone [x]"},
    )

    assert rendered == r"Escaped=Hello\` @​everyone \[x\] Raw=Hello` @everyone [x] Code=`Hello´ @everyone [x]`"


def test_localizer_formats_localized_lists() -> None:
    localizer = Localizer(
        catalogs={
            "english": {
                "example": {
                    "items": {
                        "item_format": "<{RAW:LIST_ITEM}>",
                        "separator": ", ",
                    }
                }
            }
        }
    )

    rendered = localizer.format_list("<{RAW:LIST_ITEM}>", ", ", ["one", "two"])

    assert rendered == "<one>, <two>"


def test_localizer_uses_list_metadata_from_template_entries() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer.text(
        "results.validation_detail.unsupported_language",
        language="english",
        LANGUAGES=["english", "german"],
    )

    assert rendered == "Unsupported language. Available languages: `english`, `german`"


def test_build_result_uses_list_metadata_from_result_entries() -> None:
    localizer = Localizer.from_directory()

    result = build_result(
        localizer,
        "results.permission.granted",
        language="english",
        USER="<@1>",
        TARGET="<@2>",
        PERMISSIONS=["View", "Edit"],
    )

    assert result.message.endswith("- View\n- Edit")


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
