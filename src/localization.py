"""Runtime localization helpers backed by JSON language files."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from src.utils.discord_text import escape_discord_text, normalize_discord_code_value

DEFAULT_LANGUAGE = "english"
_LANG_DIRECTORY = Path(__file__).resolve().parent.parent / "lang"
_DEFAULT_TIMESTAMP_FORMAT = "%d-%m-%Y %H:%M:%S %Z"
_DEFAULT_UNKNOWN_TIMESTAMP = "unknown"


class LocalizationError(ValueError):
    """Raised when a translation catalog is invalid or a lookup fails."""

    @classmethod
    def translation_key_not_object(cls, key: str) -> LocalizationError:
        """Build an error for embed/result entries that must be JSON objects."""
        return cls(f"Translation key {key!r} is not an object.")

    @classmethod
    def translation_result_missing_strings(cls, key: str) -> LocalizationError:
        """Build an error for structured entries missing their text fields."""
        return cls(f"Translation result {key!r} must contain string title/body/footer.")

    @classmethod
    def translation_result_invalid_placeholders(cls, key: str) -> LocalizationError:
        """Build an error for structured entries with malformed placeholder specs."""
        return cls(f"Translation result {key!r} must contain object placeholders when provided.")

    @classmethod
    def language_file_not_object(cls, file_name: str) -> LocalizationError:
        """Build an error for language files that are not JSON objects."""
        return cls(f"Language file {file_name} must contain a JSON object.")

    @classmethod
    def default_language_missing(cls, language: str) -> LocalizationError:
        """Build an error for missing default language catalogs."""
        return cls(f"Missing required default language catalog: {language}.json")

    @classmethod
    def translation_key_not_string(cls, key: str) -> LocalizationError:
        """Build an error for string lookups that point to structured data."""
        return cls(f"Translation key {key!r} is not a string.")

    @classmethod
    def unsupported_language(cls, language: str) -> LocalizationError:
        """Build an error for language identifiers without a loaded catalog."""
        return cls(f"Unsupported language: {language}")

    @classmethod
    def template_entry_missing_template(cls) -> LocalizationError:
        """Build an error for malformed template entries."""
        return cls("Template entries must contain a string `template` field.")

    @classmethod
    def template_entry_invalid_placeholders(cls) -> LocalizationError:
        """Build an error for malformed template placeholder metadata."""
        return cls("Template entry `placeholders` must be an object when provided.")

    @classmethod
    def unknown_translation_key(cls, key: str) -> LocalizationError:
        """Build an error for missing translation paths."""
        return cls(f"Unknown translation key: {key}")

    @classmethod
    def placeholder_name_contains_backslash(cls) -> LocalizationError:
        """Build an error for invalid placeholder syntax."""
        return cls("Backslashes are not allowed inside placeholder names.")

    @classmethod
    def unclosed_placeholder(cls, template: str) -> LocalizationError:
        """Build an error for templates with an opening placeholder brace only."""
        return cls(f"Unclosed placeholder in template: {template!r}")

    @classmethod
    def empty_placeholder_name(cls) -> LocalizationError:
        """Build an error for empty placeholder names."""
        return cls("Empty placeholder names are not allowed.")

    @classmethod
    def unsupported_placeholder_mode(cls, mode: str) -> LocalizationError:
        """Build an error for unknown placeholder render modes."""
        return cls(f"Unsupported placeholder mode {mode!r}.")

    @classmethod
    def placeholder_spec_not_object(cls, name: str) -> LocalizationError:
        """Build an error for malformed placeholder specs."""
        return cls(f"Placeholder spec for {name!r} must be an object.")

    @classmethod
    def placeholder_path_invalid(cls, name: str) -> LocalizationError:
        """Build an error for placeholder specs with invalid source paths."""
        return cls(f"Placeholder path for {name!r} must be a non-empty string.")

    @classmethod
    def placeholder_list_spec_not_object(cls, name: str) -> LocalizationError:
        """Build an error for malformed list placeholder specs."""
        return cls(f"Placeholder list spec for {name!r} must be an object.")

    @classmethod
    def placeholder_list_spec_invalid_format(cls, name: str) -> LocalizationError:
        """Build an error for list specs missing item format metadata."""
        return cls(f"Placeholder list spec for {name!r} must define string item_format/separator.")

    @classmethod
    def placeholder_list_value_not_sequence(cls, name: str) -> LocalizationError:
        """Build an error for list placeholders receiving scalar values."""
        return cls(f"Placeholder {name!r} must be a list or tuple for list formatting.")

    @classmethod
    def placeholder_lookup_missing_key(cls, name: str, value: str) -> LocalizationError:
        """Build an error for lookup specs missing one runtime value."""
        return cls(f"Lookup spec for {name!r} is missing a translation key for {value!r}.")

    @classmethod
    def placeholder_lookup_invalid(cls, name: str) -> LocalizationError:
        """Build an error for malformed lookup placeholder specs."""
        return cls(f"Placeholder lookup spec for {name!r} must be a string or object.")

    @classmethod
    def source_value_missing(cls, path: str) -> LocalizationError:
        """Build an error for placeholders whose source path cannot be resolved."""
        return cls(f"Missing source value for {path!r}.")

    @classmethod
    def invalid_timestamp_placeholder(cls, value: object) -> LocalizationError:
        """Build an error for strict timestamp placeholders with invalid values."""
        return cls(f"Timestamp placeholder value {value!r} is not valid ISO-8601 data.")

    @classmethod
    def timestamp_format_not_string(cls) -> LocalizationError:
        """Build an error for malformed timestamp format settings."""
        return cls("common.formats.timestamp must be a string.")

    @classmethod
    def unknown_timestamp_not_string(cls) -> LocalizationError:
        """Build an error for malformed unknown timestamp fallback settings."""
        return cls("common.formats.unknown_timestamp must be a string.")


class SupportsLanguage(Protocol):
    """Minimal contract for values that carry a persisted language setting."""

    language: str | None


@dataclass(slots=True, frozen=True)
class Localizer:
    """Resolve localized strings and raw entries from cached JSON catalogs."""

    catalogs: dict[str, dict[str, object]]
    default_language: str = DEFAULT_LANGUAGE

    @classmethod
    def from_directory(cls, directory: Path = _LANG_DIRECTORY) -> Localizer:
        """Load every JSON language catalog from one directory into memory."""
        catalogs: dict[str, dict[str, object]] = {}
        for path in sorted(directory.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                payload: object = json.load(handle)
            if not isinstance(payload, dict):
                raise LocalizationError.language_file_not_object(path.name)
            catalogs[path.stem.lower()] = payload
        if DEFAULT_LANGUAGE not in catalogs:
            raise LocalizationError.default_language_missing(DEFAULT_LANGUAGE)
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

    def resolve_language(self, language: str | None) -> str:
        """Resolve one persisted language value against the available catalogs."""
        language = self.normalize_language(language)
        return language if language in self.catalogs else self.default_language

    def language_for_thread(self, thread: SupportsLanguage | None) -> str:
        """Resolve the effective language for one persisted Discord thread."""
        if thread is None:
            return self.default_language
        return self.resolve_language(thread.language)

    def text(
        self,
        key: str,
        *,
        language: str | None = None,
        sources: Mapping[str, object] | None = None,
    ) -> str:
        """Resolve one localized string and interpolate its placeholders."""
        value = self.value(key, language=language)
        if isinstance(value, str):
            return self.render(value, sources=sources)
        if self._is_template_entry(value):
            return self._render_template_entry(value, language=language, sources=dict(sources or {}))
        raise LocalizationError.translation_key_not_string(key)

    def lookup(self, key_prefix: str, value: object, *, language: str | None = None) -> str:
        """Resolve one language key from a base path plus one runtime value."""
        normalized_value = self._normalize_lookup_value(value)
        return self.text(f"{key_prefix}.{normalized_value}", language=language)

    def value(self, key: str, *, language: str | None = None) -> object:
        """Resolve one raw localized entry from the active catalog."""
        catalog_language = self.normalize_language(language)
        catalog = self.catalogs.get(catalog_language)
        if catalog is None:
            raise LocalizationError.unsupported_language(catalog_language)
        return self._lookup(catalog, key)

    def render(
        self,
        template: str,
        *,
        sources: Mapping[str, object] | None = None,
    ) -> str:
        """Render one already-resolved template string with placeholders."""
        return self._interpolate(template, dict(sources or {}), language=None, placeholder_specs=None)

    def render_with_placeholders(
        self,
        template: str,
        *,
        language: str | None = None,
        sources: Mapping[str, object] | None = None,
        placeholders: dict[str, object] | None = None,
        placeholder_specs: dict[str, object] | None = None,
    ) -> str:
        """Render one template with optional placeholder-format metadata from the catalog."""
        merged_sources = self._merge_sources(sources, placeholders)
        return self._interpolate(
            template,
            merged_sources,
            language=language,
            placeholder_specs=placeholder_specs,
        )

    def format_list(
        self,
        item_format: str,
        separator: str,
        items: list[dict[str, object] | object] | tuple[dict[str, object] | object, ...],
        *,
        language: str | None = None,
        sources: Mapping[str, object] | None = None,
    ) -> str:
        """Render one localized list by formatting each item and joining them."""
        rendered_items: list[str] = []
        shared_sources = dict(sources or {})
        for item in items:
            item_sources = dict(shared_sources)
            item_sources["item"] = item
            rendered_items.append(
                self._interpolate(
                    item_format,
                    item_sources,
                    language=language,
                    placeholder_specs=None,
                )
            )
        return separator.join(rendered_items)

    def _render_template_entry(
        self,
        entry: dict[str, object],
        *,
        language: str | None,
        sources: Mapping[str, object],
    ) -> str:
        template = entry.get("template")
        placeholder_specs = entry.get("placeholders")
        if not isinstance(template, str):
            raise LocalizationError.template_entry_missing_template()
        if placeholder_specs is not None and not isinstance(placeholder_specs, dict):
            raise LocalizationError.template_entry_invalid_placeholders()
        return self.render_with_placeholders(
            template,
            language=language,
            sources=sources,
            placeholder_specs=placeholder_specs,
        )

    @staticmethod
    def _merge_sources(
        *sources: Mapping[str, object] | dict[str, object] | None,
    ) -> dict[str, object]:
        merged: dict[str, object] = {}
        for source in sources:
            if source is None:
                continue
            merged.update(source)
        return merged

    @staticmethod
    def _is_template_entry(value: object) -> bool:
        return isinstance(value, dict) and "template" in value

    @staticmethod
    def _lookup(catalog: dict[str, object], key: str) -> object:
        current: object = catalog
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                raise LocalizationError.unknown_translation_key(key)
            current = current[part]
        return current

    def _interpolate(
        self,
        template: str,
        sources: Mapping[str, object],
        *,
        language: str | None,
        placeholder_specs: dict[str, object] | None,
    ) -> str:
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
                    raise LocalizationError.placeholder_name_contains_backslash()
                end_index += 1
            if end_index >= length:
                raise LocalizationError.unclosed_placeholder(template)
            raw_name = template[index + 1 : end_index]
            if not raw_name:
                raise LocalizationError.empty_placeholder_name()
            mode, name = self._parse_placeholder(raw_name)
            spec = self._placeholder_spec(name, placeholder_specs)
            value = self._resolve_placeholder_value(name, sources, spec)
            value = self._transform_placeholder_value(name, value, spec, language=language, sources=sources)
            parts.append(self._render_placeholder_value(mode, value, language=language))
            index = end_index + 1
        return "".join(parts)

    @staticmethod
    def _parse_placeholder(raw_name: str) -> tuple[str, str]:
        if ":" not in raw_name:
            return "escaped", raw_name.strip()
        mode, name = raw_name.split(":", 1)
        normalized_mode = mode.strip().lower()
        normalized_name = name.strip()
        if normalized_mode not in {"escaped", "raw", "code", "timestamp"}:
            raise LocalizationError.unsupported_placeholder_mode(mode)
        if not normalized_name:
            raise LocalizationError.empty_placeholder_name()
        return normalized_mode, normalized_name

    @staticmethod
    def _placeholder_spec(name: str, placeholder_specs: dict[str, object] | None) -> dict[str, object] | None:
        if placeholder_specs is None:
            return None
        spec = placeholder_specs.get(name)
        if spec is None:
            return None
        if not isinstance(spec, dict):
            raise LocalizationError.placeholder_spec_not_object(name)
        return spec

    def _resolve_placeholder_value(
        self,
        name: str,
        sources: Mapping[str, object],
        spec: dict[str, object] | None,
    ) -> object:
        path = name
        if spec is not None:
            spec_path = spec.get("path")
            if spec_path is not None:
                if not isinstance(spec_path, str) or not spec_path.strip():
                    raise LocalizationError.placeholder_path_invalid(name)
                path = spec_path.strip()
        return self._resolve_source_path(path, sources)

    def _transform_placeholder_value(
        self,
        name: str,
        value: object,
        spec: dict[str, object] | None,
        *,
        language: str | None,
        sources: Mapping[str, object],
    ) -> object:
        if spec is None:
            return value
        list_spec = spec.get("list")
        if list_spec is not None:
            if not isinstance(list_spec, dict):
                raise LocalizationError.placeholder_list_spec_not_object(name)
            item_format = list_spec.get("item_format")
            separator = list_spec.get("separator")
            if not isinstance(item_format, str) or not isinstance(separator, str):
                raise LocalizationError.placeholder_list_spec_invalid_format(name)
            if not isinstance(value, list | tuple):
                raise LocalizationError.placeholder_list_value_not_sequence(name)
            value = self.format_list(
                item_format,
                separator,
                value,
                language=language,
                sources=sources,
            )

        lookup_spec = spec.get("lookup")
        if lookup_spec is not None:
            value = self._lookup_placeholder_value(name, value, lookup_spec, language=language)

        timestamp_spec = spec.get("timestamp")
        if timestamp_spec is not None:
            value = self._format_timestamp_value(value, language=language, spec=timestamp_spec)
        return value

    def _lookup_placeholder_value(
        self,
        name: str,
        value: object,
        lookup_spec: object,
        *,
        language: str | None,
    ) -> str:
        if isinstance(lookup_spec, str):
            return self.lookup(lookup_spec, value, language=language)
        if isinstance(lookup_spec, dict):
            normalized_value = self._normalize_lookup_value(value)
            target_key = lookup_spec.get(normalized_value)
            if not isinstance(target_key, str):
                raise LocalizationError.placeholder_lookup_missing_key(name, normalized_value)
            return self.text(target_key, language=language)
        raise LocalizationError.placeholder_lookup_invalid(name)

    @staticmethod
    def _resolve_source_path(path: str, sources: Mapping[str, object]) -> object:
        if path in sources:
            return sources[path]
        current: object = sources
        for part in path.split("."):
            if isinstance(current, Mapping):
                if part not in current:
                    raise LocalizationError.source_value_missing(path)
                current = current[part]
                continue
            if hasattr(current, part):
                current = getattr(current, part)
                continue
            raise LocalizationError.source_value_missing(path)
        return current

    def _format_timestamp_value(
        self,
        value: object,
        *,
        language: str | None,
        spec: object,
    ) -> str:
        if value is None:
            return self._unknown_timestamp(language)
        if isinstance(value, datetime):
            parsed = value
        else:
            rendered_value = str(value).strip()
            if not rendered_value:
                return self._unknown_timestamp(language)
            try:
                parsed = datetime.fromisoformat(rendered_value)
            except ValueError as error:
                if spec is True:
                    return rendered_value
                raise LocalizationError.invalid_timestamp_placeholder(value) from error
        return parsed.strftime(self._timestamp_format(language)).strip() or parsed.isoformat(sep=" ", timespec="seconds")

    def _timestamp_format(self, language: str | None) -> str:
        try:
            value = self.value("common.formats.timestamp", language=language)
        except LocalizationError:
            return _DEFAULT_TIMESTAMP_FORMAT
        if not isinstance(value, str):
            raise LocalizationError.timestamp_format_not_string()
        return value

    def _unknown_timestamp(self, language: str | None) -> str:
        try:
            value = self.value("common.formats.unknown_timestamp", language=language)
        except LocalizationError:
            return _DEFAULT_UNKNOWN_TIMESTAMP
        if not isinstance(value, str):
            raise LocalizationError.unknown_timestamp_not_string()
        return value

    @staticmethod
    def _normalize_lookup_value(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value).strip().lower()

    def _render_placeholder_value(self, mode: str, value: object, *, language: str | None) -> str:
        if mode == "timestamp":
            return self._format_timestamp_value(value, language=language, spec=True)

        rendered = str(value)
        if mode == "raw":
            return rendered
        if mode == "code":
            return normalize_discord_code_value(rendered)
        return escape_discord_text(rendered)
