from __future__ import annotations

import json

import pytest

from src.discord_results import build_result
from src.localization import LocalizationError, Localizer


def test_localizer_resolves_sources_with_dot_paths_and_backslash_escaping() -> None:
    localizer = Localizer(
        catalogs={
            "english": {
                "example": {
                    "body": "Language now {view.language_name}",
                }
            }
        }
    )

    rendered = localizer.text("example.body", language="english", sources={"view": {"language_name": "German"}})
    escaped = localizer.render(
        r"Literal \{name\} and \\ and {view.value}",
        sources={"view": {"value": "ok"}},
    )

    assert "German" in rendered
    assert "{view.language_name}" not in rendered
    assert "{name}" in escaped
    assert escaped.endswith("ok")


def test_localizer_supports_explicit_placeholder_modes_with_dot_paths() -> None:
    localizer = Localizer.from_directory()

    rendered = localizer.render(
        "Escaped={view.value} Raw={RAW:view.value} Code=`{CODE:view.value}` Mention=<@{RAW:view.user_id}>",
        sources={"view": {"value": "Hello` @everyone [x]", "user_id": 123}},
    )

    assert r"Escaped=Hello\` @" in rendered
    assert "Raw=Hello` @everyone [x]" in rendered
    assert "Code=`Hello" in rendered
    assert "Mention=<@123>" in rendered


def test_localizer_formats_localized_lists_with_item_sources() -> None:
    localizer = Localizer(
        catalogs={
            "english": {
                "example": {
                    "items": {
                        "template": "{RAW:view.items}",
                        "placeholders": {
                            "view.items": {
                                "list": {
                                    "item_format": "<{RAW:item}>",
                                    "separator": ", ",
                                }
                            }
                        },
                    }
                }
            }
        }
    )

    rendered = localizer.text("example.items", language="english", sources={"view": {"items": ["one", "two"]}})

    assert rendered == "<one>, <two>"


def test_localizer_supports_lookup_and_timestamp_specs() -> None:
    localizer = Localizer(
        catalogs={
            "english": {
                "common": {
                    "formats": {
                        "timestamp": "%d-%m-%Y %H:%M:%S",
                        "unknown_timestamp": "unknown",
                    }
                },
                "labels": {
                    "mode": {
                        "regex": "Regex",
                    }
                },
                "example": {
                    "body": {
                        "template": "{value} <@{RAW:view.user_id}> {expires_at}",
                        "placeholders": {
                            "value": {"path": "view.mode", "lookup": {"regex": "labels.mode.regex"}},
                            "expires_at": {"path": "view.expires_at", "timestamp": True},
                        },
                    }
                },
            }
        }
    )

    rendered = localizer.text(
        "example.body",
        language="english",
        sources={"view": {"mode": "regex", "user_id": 123, "expires_at": "2026-06-06T12:34:56+00:00"}},
    )

    assert rendered == "Regex <@123> 06-06-2026 12:34:56"


def test_build_result_uses_sources_with_list_metadata() -> None:
    localizer = Localizer(
        catalogs={
            "english": {
                "results": {
                    "example": {
                        "granted": {
                            "title": "Done",
                            "body": "<@{RAW:view.user_id}> -> <@{RAW:view.target_id}>\n{RAW:view.permissions}",
                            "footer": "",
                            "placeholders": {
                                "view.permissions": {
                                    "list": {
                                        "item_format": "- {RAW:item}",
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
        sources={"view": {"user_id": 1, "target_id": 2, "permissions": ["View", "Edit"]}},
    )

    assert result.message.endswith("- View\n- Edit")


def test_localizer_loads_utf8_german_text_from_files(tmp_path) -> None:
    german_text = "verfügbar außer äöüß"
    (tmp_path / "english.json").write_text("{}", encoding="utf-8")
    (tmp_path / "german.json").write_text(
        json.dumps({"example": {"text": german_text}}, ensure_ascii=False),
        encoding="utf-8",
    )

    localizer = Localizer.from_directory(tmp_path)
    rendered = localizer.text("example.text", language="german")

    assert rendered == german_text


def test_localizer_raises_for_missing_source_values() -> None:
    localizer = Localizer(catalogs={"english": {"example": {"body": "Hello {view.display_name}"}}})

    with pytest.raises(LocalizationError):
        localizer.text("example.body", language="english", sources={"view": {}})
