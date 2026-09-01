from __future__ import annotations

import ast
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


def test_slash_command_metadata_uses_localization_keys() -> None:
    command_root = REPO_ROOT / "src" / "entrypoints" / "discord" / "commands"
    violations: list[str] = []
    for path in sorted(command_root.glob("*_commands.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = _ast_call_name(node.func)
            if call_name == "discord.app_commands.Group":
                _collect_literal_keyword_violations(
                    violations,
                    path=path,
                    node=node,
                    keyword_names={"description"},
                )
                continue
            if call_name == "discord.app_commands.Choice":
                _collect_literal_keyword_violations(
                    violations,
                    path=path,
                    node=node,
                    keyword_names={"name"},
                )
                continue
            if call_name.endswith(".command") or call_name == "discord.app_commands.describe":
                _collect_literal_keyword_violations(
                    violations,
                    path=path,
                    node=node,
                    keyword_names={"description"},
                )

    assert not violations, f"Found hardcoded slash-command metadata: {', '.join(violations)}"


def test_slash_command_metadata_catalogs_are_complete_and_discord_sized() -> None:
    catalogs = {
        language: json.loads((REPO_ROOT / "lang" / f"{language}.json").read_text(encoding="utf-8")) for language in ("english", "german")
    }
    english_commands = catalogs["english"]["discord"]["commands"]
    german_commands = catalogs["german"]["discord"]["commands"]
    english_paths = _leaf_paths(english_commands)
    german_paths = _leaf_paths(german_commands)

    assert english_paths == german_paths

    violations: list[str] = []
    for language, commands in (("english", english_commands), ("german", german_commands)):
        for path in _leaf_paths(commands):
            value = _lookup_path(commands, path)
            if not isinstance(value, str):
                violations.append(f"{language}:{'.'.join(path)} is not text")
                continue
            if len(value) > 100:
                violations.append(f"{language}:{'.'.join(path)} is longer than 100 chars")

    assert not violations, f"Invalid slash-command metadata: {', '.join(violations)}"


def _ast_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _ast_call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _collect_literal_keyword_violations(
    violations: list[str],
    *,
    path: Path,
    node: ast.Call,
    keyword_names: set[str],
) -> None:
    violations.extend(
        f"{path.name}:{keyword.value.lineno}"
        for keyword in node.keywords
        if keyword.arg in keyword_names and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)
    )


def _leaf_paths(value: object, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if not isinstance(value, dict):
        return {prefix}
    paths: set[tuple[str, ...]] = set()
    for key, nested_value in value.items():
        paths.update(_leaf_paths(nested_value, (*prefix, str(key))))
    return paths


def _lookup_path(value: object, path: tuple[str, ...]) -> object:
    current = value
    for part in path:
        assert isinstance(current, dict)
        current = current[part]
    return current


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
        violations.extend(
            f"{path.name}: contains {needle}" for needle in ('"`{', "'`{", 'f"`{', 'f"**{', '"\\n- ".join', '", ".join(') if needle in text
        )

    assert not violations, f"Found hardcoded runtime formatting in migrated layers: {', '.join(violations)}"


def test_localized_discord_scopes_do_not_use_removed_shared_keys() -> None:
    legacy_placeholder_pattern = re.compile(r"\{(?:RAW:|CODE:|TIMESTAMP:)?[A-Z][A-Z0-9_]*(?:\.[A-Za-z0-9_]+)?\}")
    for language in ("german", "english"):
        catalog_path = REPO_ROOT / "lang" / f"{language}.json"
        rendered = catalog_path.read_text(encoding="utf-8")
        catalog = json.loads(rendered)

        assert "common" in catalog
        assert legacy_placeholder_pattern.search(rendered) is None
        assert "LIST_ITEM" not in rendered
        assert "SECTION_LIST" not in rendered
        assert "USER_LIST" not in rendered
        assert "PERMISSION_LIST" not in rendered
