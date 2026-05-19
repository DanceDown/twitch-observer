"""Runtime localization helpers backed by JSON language files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.database.records import ThreadRecord
from src.utils.discord_text import escape_discord_text, normalize_discord_code_value

DEFAULT_LANGUAGE = "english"
_LANG_DIRECTORY = Path(__file__).resolve().parent.parent / "lang"
DEFAULT_LIST_ITEM_PLACEHOLDER = "LIST_ITEM"


class LocalizationError(ValueError):
    """Raised when a translation catalog is invalid or a lookup fails."""


@dataclass(slots=True, frozen=True)
class Localizer:
    """Resolve localized strings and raw entries from cached JSON catalogs."""

    catalogs: dict[str, dict[str, Any]]
    default_language: str = DEFAULT_LANGUAGE

    @classmethod
    def from_directory(cls, directory: Path = _LANG_DIRECTORY) -> Localizer:
        """Load every JSON language catalog from one directory into memory."""
        catalogs: dict[str, dict[str, Any]] = {}
        for path in sorted(directory.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise LocalizationError(f"Language file {path.name} must contain a JSON object.")
            catalogs[path.stem.lower()] = payload
        if DEFAULT_LANGUAGE not in catalogs:
            raise LocalizationError(f"Missing required default language catalog: {DEFAULT_LANGUAGE}.json")
        return cls(catalogs=catalogs)

    def available_languages(self) -> tuple[str, ...]:
        """Return all configured language identifiers."""
        return tuple(sorted(self.catalogs))

    def normalize_language(self, language: str | None) -> str:
        """Normalize a language identifier and fall back to the default language."""
        if language is None:
            return self.default_language
        normalized = language.strip().lower()
        return normalized or self.default_language

    def has_language(self, language: str | None) -> bool:
        """Return whether one configured catalog exists for the requested language."""
        return self.normalize_language(language) in self.catalogs

    def language_for_thread(self, thread: ThreadRecord | None) -> str:
        """Resolve the effective language for one persisted Discord thread."""
        if thread is None:
            return self.default_language
        language = self.normalize_language(thread.language)
        return language if language in self.catalogs else self.default_language

    def text(self, key: str, *, language: str | None = None, **placeholders: object) -> str:
        """Resolve one localized string and interpolate its placeholders."""
        value = self.value(key, language=language)
        if isinstance(value, str):
            return self.render(value, **placeholders)
        if self._is_template_entry(value):
            return self._render_template_entry(value, language=language, placeholders=placeholders)
        raise LocalizationError(f"Translation key {key!r} is not a string.")

    def value(self, key: str, *, language: str | None = None) -> Any:
        """Resolve one raw localized entry from the active catalog."""
        catalog_language = self.normalize_language(language)
        catalog = self.catalogs.get(catalog_language)
        if catalog is None:
            raise LocalizationError(f"Unsupported language: {catalog_language}")
        return self._lookup(catalog, key)

    def render(self, template: str, **placeholders: object) -> str:
        """Render one already-resolved template string with placeholders."""
        return self._interpolate(template, placeholders)

    def render_with_placeholders(
        self,
        template: str,
        *,
        language: str | None = None,
        placeholders: dict[str, object],
        placeholder_specs: dict[str, Any] | None = None,
    ) -> str:
        """Render one template with optional placeholder-format metadata from the catalog."""
        return self.render(template, **self._prepare_placeholders(placeholders, language=language, placeholder_specs=placeholder_specs))

    def format_list(
        self,
        item_format: str,
        separator: str,
        items: list[dict[str, object] | object] | tuple[dict[str, object] | object, ...],
        **shared_placeholders: object,
    ) -> str:
        """Render one localized list by formatting each item and joining them."""
        rendered_items: list[str] = []
        for item in items:
            placeholders = dict(shared_placeholders)
            if isinstance(item, dict):
                placeholders.update(item)
            else:
                placeholders[DEFAULT_LIST_ITEM_PLACEHOLDER] = item
            rendered_items.append(self._interpolate(item_format, placeholders))
        return separator.join(rendered_items)

    def _render_template_entry(
        self,
        entry: dict[str, Any],
        *,
        language: str | None,
        placeholders: dict[str, object],
    ) -> str:
        template = entry.get("template")
        placeholder_specs = entry.get("placeholders")
        if not isinstance(template, str):
            raise LocalizationError("Template entries must contain a string `template` field.")
        if placeholder_specs is not None and not isinstance(placeholder_specs, dict):
            raise LocalizationError("Template entry `placeholders` must be an object when provided.")
        return self.render_with_placeholders(
            template,
            language=language,
            placeholders=placeholders,
            placeholder_specs=placeholder_specs,
        )

    def _prepare_placeholders(
        self,
        placeholders: dict[str, object],
        *,
        language: str | None,
        placeholder_specs: dict[str, Any] | None,
    ) -> dict[str, object]:
        prepared = dict(placeholders)
        if placeholder_specs is None:
            return prepared
        for name, spec in placeholder_specs.items():
            if name not in prepared:
                continue
            if not isinstance(spec, dict):
                raise LocalizationError(f"Placeholder spec for {name!r} must be an object.")
            list_spec = spec.get("list")
            if list_spec is None:
                continue
            if not isinstance(list_spec, dict):
                raise LocalizationError(f"Placeholder list spec for {name!r} must be an object.")
            item_format = list_spec.get("item_format")
            separator = list_spec.get("separator")
            if not isinstance(item_format, str) or not isinstance(separator, str):
                raise LocalizationError(f"Placeholder list spec for {name!r} must define string item_format/separator.")
            value = prepared[name]
            if not isinstance(value, list | tuple):
                raise LocalizationError(f"Placeholder {name!r} must be a list or tuple for list formatting.")
            prepared[name] = self.format_list(item_format, separator, value)
        return prepared

    @staticmethod
    def _is_template_entry(value: object) -> bool:
        return isinstance(value, dict) and "template" in value

    @staticmethod
    def _lookup(catalog: dict[str, Any], key: str) -> Any:
        current: Any = catalog
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                raise LocalizationError(f"Unknown translation key: {key}")
            current = current[part]
        return current

    @staticmethod
    def _interpolate(template: str, placeholders: dict[str, object]) -> str:
        parts: list[str] = []
        index = 0
        length = len(template)
        while index < length:
            char = template[index]
            if char == "\\":
                if index + 1 < length:
                    parts.append(template[index + 1])
                    index += 2
                else:
                    parts.append("\\")
                    index += 1
                continue
            if char != "{":
                parts.append(char)
                index += 1
                continue
            end_index = index + 1
            while end_index < length and template[end_index] != "}":
                if template[end_index] == "\\":
                    raise LocalizationError("Backslashes are not allowed inside placeholder names.")
                end_index += 1
            if end_index >= length:
                raise LocalizationError(f"Unclosed placeholder in template: {template!r}")
            raw_name = template[index + 1 : end_index]
            if not raw_name:
                raise LocalizationError("Empty placeholder names are not allowed.")
            mode, name = Localizer._parse_placeholder(raw_name)
            if name not in placeholders:
                raise LocalizationError(f"Missing placeholder value for {name!r}.")
            value = placeholders[name]
            parts.append(Localizer._render_placeholder_value(mode, value))
            index = end_index + 1
        return "".join(parts)

    @staticmethod
    def _parse_placeholder(raw_name: str) -> tuple[str, str]:
        if ":" not in raw_name:
            return "escaped", raw_name
        mode, name = raw_name.split(":", 1)
        normalized_mode = mode.strip().lower()
        normalized_name = name.strip()
        if normalized_mode not in {"escaped", "raw", "code"}:
            raise LocalizationError(f"Unsupported placeholder mode {mode!r}.")
        if not normalized_name:
            raise LocalizationError("Empty placeholder names are not allowed.")
        return normalized_mode, normalized_name

    @staticmethod
    def _render_placeholder_value(mode: str, value: object) -> str:
        rendered = str(value)
        if mode == "raw":
            return rendered
        if mode == "code":
            return normalize_discord_code_value(rendered)
        return escape_discord_text(rendered)
