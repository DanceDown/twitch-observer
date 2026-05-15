"""Runtime localization helpers backed by JSON language files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.database.records import ThreadRecord
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.utils.discord_text import escape_discord_text, normalize_discord_code_value

DEFAULT_LANGUAGE = "english"
_LANG_DIRECTORY = Path(__file__).resolve().parent.parent / "lang"
DEFERRED_PLACEHOLDER_TOKENS: dict[str, str] = {
    "USER": "\u0000LOCALIZER_USER\u0000",
}
DEFAULT_LIST_ITEM_PLACEHOLDER = "ITEM"


class LocalizationError(ValueError):
    """Raised when a translation catalog is invalid or a lookup fails."""


def resolve_deferred_placeholders(template: str, **placeholders: object) -> str:
    """Resolve placeholders intentionally deferred until one later rendering step."""
    rendered = template
    for name, token in DEFERRED_PLACEHOLDER_TOKENS.items():
        if name in placeholders:
            rendered = rendered.replace(token, str(placeholders[name]))
    return rendered


@dataclass(slots=True, frozen=True)
class Localizer:
    """Resolve localized strings and command results from cached JSON catalogs."""

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

    def text(
        self,
        key: str,
        *,
        language: str | None = None,
        **placeholders: object,
    ) -> str:
        """Resolve one localized string and interpolate its placeholders."""
        catalog_language = self.normalize_language(language)
        catalog = self.catalogs.get(catalog_language)
        if catalog is None:
            raise LocalizationError(f"Unsupported language: {catalog_language}")
        value = self._lookup(catalog, key)
        if not isinstance(value, str):
            raise LocalizationError(f"Translation key {key!r} in {catalog_language} is not a string.")
        return self._interpolate(value, placeholders)

    def result(
        self,
        key: str,
        *,
        language: str | None = None,
        style: DiscordResultStyle = DiscordResultStyle.INFO,
        ephemeral: bool = False,
        thumbnail_url: str | None = None,
        **placeholders: object,
    ) -> DiscordCommandResult:
        """Resolve a localized command result object with `title` and `message`."""
        catalog_language = self.normalize_language(language)
        catalog = self.catalogs.get(catalog_language)
        if catalog is None:
            raise LocalizationError(f"Unsupported language: {catalog_language}")
        value = self._lookup(catalog, key)
        if not isinstance(value, dict):
            raise LocalizationError(f"Translation key {key!r} in {catalog_language} is not an object.")
        title = value.get("title")
        message = value.get("message")
        if not isinstance(title, str) or not isinstance(message, str):
            raise LocalizationError(f"Translation result {key!r} in {catalog_language} must contain string title/message.")
        return DiscordCommandResult(
            title=self._interpolate(title, placeholders),
            message=self._interpolate(message, placeholders),
            style=style,
            ephemeral=ephemeral,
            thumbnail_url=thumbnail_url,
        )

    def format_list(
        self,
        key: str,
        items: list[dict[str, object] | object] | tuple[dict[str, object] | object, ...],
        *,
        language: str | None = None,
        **shared_placeholders: object,
    ) -> str:
        """Render one reusable localized list/wrapper object from the catalog."""
        catalog_language = self.normalize_language(language)
        catalog = self.catalogs.get(catalog_language)
        if catalog is None:
            raise LocalizationError(f"Unsupported language: {catalog_language}")
        value = self._lookup(catalog, key)
        if not isinstance(value, dict):
            raise LocalizationError(f"Translation key {key!r} in {catalog_language} is not an object.")

        item_format = value.get("item_format")
        separator = value.get("separator")
        prefix = value.get("prefix", "")
        suffix = value.get("suffix", "")
        empty = value.get("empty")
        if not isinstance(item_format, str) or not isinstance(separator, str):
            raise LocalizationError(f"List format {key!r} in {catalog_language} must contain string item_format/separator.")
        if not isinstance(prefix, str) or not isinstance(suffix, str):
            raise LocalizationError(f"List format {key!r} in {catalog_language} must contain string prefix/suffix.")
        if empty is not None and not isinstance(empty, str):
            raise LocalizationError(f"List format {key!r} in {catalog_language} must contain string empty when provided.")

        rendered_items: list[str] = []
        for item in items:
            placeholders = dict(shared_placeholders)
            if isinstance(item, dict):
                placeholders.update(item)
            else:
                placeholders[DEFAULT_LIST_ITEM_PLACEHOLDER] = item
            rendered_items.append(self._interpolate(item_format, placeholders))

        if not rendered_items:
            if empty is not None:
                return self._interpolate(empty, shared_placeholders)
            return self._interpolate(prefix + suffix, shared_placeholders)

        body = separator.join(rendered_items)
        return self._interpolate(prefix, shared_placeholders) + body + self._interpolate(suffix, shared_placeholders)

    def thread_result(
        self,
        key: str,
        *,
        thread: ThreadRecord | None,
        style: DiscordResultStyle = DiscordResultStyle.INFO,
        ephemeral: bool = False,
        thumbnail_url: str | None = None,
        **placeholders: object,
    ) -> DiscordCommandResult:
        """Resolve a localized command result using the language configured on one thread."""
        return self.result(
            key,
            language=self.language_for_thread(thread),
            style=style,
            ephemeral=ephemeral,
            thumbnail_url=thumbnail_url,
            **placeholders,
        )

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
                if name in DEFERRED_PLACEHOLDER_TOKENS:
                    parts.append(DEFERRED_PLACEHOLDER_TOKENS[name])
                    index = end_index + 1
                    continue
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

