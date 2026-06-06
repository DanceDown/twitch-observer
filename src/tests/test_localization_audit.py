from __future__ import annotations

import json
import re
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
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ('"`{', "'`{", 'f"`{', 'f"**{', '"\\n- ".join', '", ".join('):
            if needle in text:
                violations.append(f"{path.name}: contains {needle}")

    assert not violations, f"Found hardcoded runtime formatting in migrated layers: {', '.join(violations)}"


def test_localized_discord_scopes_do_not_use_removed_shared_keys() -> None:
    legacy_placeholder_pattern = re.compile(r"\{(?:RAW:|CODE:|MENTION:|TIMESTAMP:)?[A-Z][A-Z0-9_]*(?:\.[A-Za-z0-9_]+)?\}")
    for language in ("german", "english"):
        catalog_path = REPO_ROOT / "lang" / f"{language}.json"
        rendered = catalog_path.read_text(encoding="utf-8")
        catalog = json.loads(rendered)

        assert "common" in catalog
        assert legacy_placeholder_pattern.search(rendered) is None
        assert "{MENTION:" not in rendered
        assert "LIST_ITEM" not in rendered
        assert "SECTION_LIST" not in rendered
        assert "USER_LIST" not in rendered
        assert "PERMISSION_LIST" not in rendered
