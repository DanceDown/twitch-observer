from __future__ import annotations

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
