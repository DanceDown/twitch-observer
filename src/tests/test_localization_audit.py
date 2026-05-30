from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_ui_buttons_use_neutral_fallback_labels() -> None:
    ui_root = REPO_ROOT / "src" / "entrypoints" / "discord" / "ui"
    violations: list[str] = []
    for path in sorted(ui_root.glob("*.py")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if '@discord.ui.button(label="' not in line:
                continue
            if '@discord.ui.button(label="_"' in line:
                continue
            violations.append(f"{path.name}:{line_number}")

    assert not violations, f"Found hardcoded runtime button labels: {', '.join(violations)}"


def test_migrated_runtime_layers_do_not_use_removed_inline_code_fix() -> None:
    targets = [
        REPO_ROOT / "src" / "services" / "patterns" / "presentation.py",
        REPO_ROOT / "src" / "services" / "patterns" / "show_service.py",
        REPO_ROOT / "src" / "services" / "permission_service.py",
    ]
    violations: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for needle in ('"`{', "'`{", 'f"`{', 'f"**{', '"\\n- ".join', '", ".join('):
            if needle in text:
                violations.append(f"{path.name}: contains {needle}")

    assert not violations, f"Found hardcoded runtime formatting in migrated layers: {', '.join(violations)}"


def test_localized_discord_scopes_do_not_use_removed_shared_keys() -> None:
    for language in ("german", "english"):
        catalog = json.loads((REPO_ROOT / "lang" / f"{language}.json").read_text(encoding="utf-8"))

        assert "common" not in catalog
        assert "common" not in catalog["discord"]["reply_ui"]
        assert "permission" not in catalog["show"]
        assert "item_prefix" not in catalog["discord"]["show_ui"]["pagination"]
        assert "sections" not in catalog["show"]
        assert "section" not in catalog["show"]
        assert "empty" not in catalog["show"]
        assert "not_joined" not in catalog["results"]
        assert "validation_error" not in catalog["results"]
        assert "twitch_api_error" not in catalog["results"]
        assert "unexpected_error" not in catalog["results"]
        assert "permission_denied" not in catalog["results"]
        assert "existing_account" not in catalog["results"]["account"]
        assert "empty_selection" not in catalog["results"]["permission"]
        assert "empty_message" not in catalog["results"]["reply"]
        assert "message_too_long" not in catalog["results"]["reply"]
        assert "unsupported_action" not in catalog["results"]["reply"]
        assert "actions" not in catalog["results"]["pattern"]
        assert "type_for" not in catalog["results"]["pattern"]
        assert "mode" not in catalog["results"]["reply"]
        assert "untitled_ping" not in catalog["discord"]["pattern_ui"]["selection"]
