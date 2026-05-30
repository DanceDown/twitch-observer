from __future__ import annotations

import json

import pytest

from src.discord_results import build_result
from src.localization import LocalizationError, Localizer


def test_localizer_interpolates_placeholders_and_supports_backslash_escaping() -> None:
    localizer = Localizer(
        catalogs={
            "english": {
                "example": {
                    "body": "Language now {LANGUAGE_NAME}",
                }
            }
        }
    )

    rendered = localizer.text(
        "example.body",
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
    localizer = Localizer(
        catalogs={
            "english": {
                "example": {
                    "supported": {
                        "template": "Supported: {RAW:LANGUAGES}",
                        "placeholders": {
                            "LANGUAGES": {
                                "list": {
                                    "item_format": "`{CODE:LIST_ITEM}`",
                                    "separator": ", ",
                                }
                            }
                        },
                    }
                }
            }
        }
    )

    rendered = localizer.text(
        "example.supported",
        language="english",
        LANGUAGES=["english", "german"],
    )

    assert rendered == "Supported: `english`, `german`"


def test_build_result_uses_list_metadata_from_result_entries() -> None:
    localizer = Localizer(
        catalogs={
            "english": {
                "results": {
                    "example": {
                        "granted": {
                            "title": "Done",
                            "body": "{RAW:USER} -> {RAW:TARGET}\n{RAW:PERMISSIONS}",
                            "footer": "",
                            "placeholders": {
                                "PERMISSIONS": {
                                    "list": {
                                        "item_format": "- {RAW:LIST_ITEM}",
                                        "separator": "\n",
                                    }
                                }
                            },
                        }
                    }
                }
            }
        }
    )

    result = build_result(
        localizer,
        "results.example.granted",
        language="english",
        USER="<@1>",
        TARGET="<@2>",
        PERMISSIONS=["View", "Edit"],
    )

    assert result.message.endswith("- View\n- Edit")


def test_localizer_loads_utf8_german_text_from_files(tmp_path) -> None:
    (tmp_path / "english.json").write_text("{}", encoding="utf-8")
    (tmp_path / "german.json").write_text(
        json.dumps({"example": {"text": "verfügbar außer äöüß"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    localizer = Localizer.from_directory(tmp_path)
    rendered = localizer.text("example.text", language="german")

    assert rendered == "verfügbar außer äöüß"


def test_localizer_raises_for_missing_placeholder_values() -> None:
    localizer = Localizer(catalogs={"english": {"example": {"body": "Hello {DISPLAY_NAME}"}}})

    with pytest.raises(LocalizationError):
        localizer.text("example.body", language="english")
