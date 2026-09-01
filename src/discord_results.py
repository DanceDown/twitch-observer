"""Helpers for building Discord-facing result objects from localized entries."""

from __future__ import annotations

from collections.abc import Mapping

from src.database.records import ThreadRecord
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import LocalizationError, Localizer


# Result builders intentionally expose all Discord embed/result presentation knobs at one call site.
def build_result(  # noqa: PLR0913
    localizer: Localizer,
    key: str,
    *,
    language: str | None = None,
    style: DiscordResultStyle = DiscordResultStyle.INFO,
    ephemeral: bool = False,
    thumbnail_url: str | None = None,
    color: str | None = None,
    author_name: str | None = None,
    author_url: str | None = None,
    author_icon_url: str | None = None,
    sources: Mapping[str, object] | None = None,
) -> DiscordCommandResult:
    """Build one Discord command result from a localized `title`/`body`/`footer` object."""
    value = localizer.value(key, language=language)
    if not isinstance(value, dict):
        raise LocalizationError.translation_key_not_object(key)
    title = value.get("title")
    body = value.get("body")
    footer = value.get("footer")
    placeholder_specs = value.get("placeholders")
    if not isinstance(title, str) or not isinstance(body, str) or not isinstance(footer, str):
        raise LocalizationError.translation_result_missing_strings(key)
    if placeholder_specs is not None and not isinstance(placeholder_specs, dict):
        raise LocalizationError.translation_result_invalid_placeholders(key)
    return DiscordCommandResult(
        title=localizer.render_with_placeholders(
            title,
            language=language,
            sources=sources,
            placeholder_specs=placeholder_specs,
        ),
        message=localizer.render_with_placeholders(
            body,
            language=language,
            sources=sources,
            placeholder_specs=placeholder_specs,
        ),
        footer=localizer.render_with_placeholders(
            footer,
            language=language,
            sources=sources,
            placeholder_specs=placeholder_specs,
        ),
        style=style,
        ephemeral=ephemeral,
        thumbnail_url=thumbnail_url,
        color=color,
        language=localizer.resolve_language(language),
        author_name=author_name,
        author_url=author_url,
        author_icon_url=author_icon_url,
    )


# Thread results mirror `build_result` and add only language/thread source resolution.
def build_thread_result(  # noqa: PLR0913
    localizer: Localizer,
    key: str,
    *,
    thread: ThreadRecord | None,
    style: DiscordResultStyle = DiscordResultStyle.INFO,
    ephemeral: bool = False,
    thumbnail_url: str | None = None,
    color: str | None = None,
    author_name: str | None = None,
    author_url: str | None = None,
    author_icon_url: str | None = None,
    sources: Mapping[str, object] | None = None,
) -> DiscordCommandResult:
    """Build one Discord command result using the language configured on a thread."""
    resolved_sources = dict(sources or {})
    if thread is not None:
        resolved_sources.setdefault("thread", thread)
    return build_result(
        localizer,
        key,
        language=localizer.language_for_thread(thread),
        style=style,
        ephemeral=ephemeral,
        thumbnail_url=thumbnail_url,
        color=color,
        author_name=author_name,
        author_url=author_url,
        author_icon_url=author_icon_url,
        sources=resolved_sources,
    )
