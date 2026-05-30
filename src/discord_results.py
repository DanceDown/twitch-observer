"""Helpers for building Discord-facing result objects from localized entries."""

from __future__ import annotations

from src.database.records import ThreadRecord
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import LocalizationError, Localizer


def build_result(
    localizer: Localizer,
    key: str,
    *,
    language: str | None = None,
    style: DiscordResultStyle = DiscordResultStyle.INFO,
    ephemeral: bool = False,
    thumbnail_url: str | None = None,
    **placeholders: object,
) -> DiscordCommandResult:
    """Build one Discord command result from a localized `title`/`body`/`footer` object."""
    value = localizer.value(key, language=language)
    if not isinstance(value, dict):
        raise LocalizationError(f"Translation key {key!r} is not an object.")
    title = value.get("title")
    body = value.get("body")
    footer = value.get("footer")
    placeholder_specs = value.get("placeholders")
    if not isinstance(title, str) or not isinstance(body, str) or not isinstance(footer, str):
        raise LocalizationError(f"Translation result {key!r} must contain string title/body/footer.")
    if placeholder_specs is not None and not isinstance(placeholder_specs, dict):
        raise LocalizationError(f"Translation result {key!r} must contain object placeholders when provided.")
    return DiscordCommandResult(
        title=localizer.render_with_placeholders(
            title,
            language=language,
            placeholders=placeholders,
            placeholder_specs=placeholder_specs,
        ),
        message=localizer.render_with_placeholders(
            body,
            language=language,
            placeholders=placeholders,
            placeholder_specs=placeholder_specs,
        ),
        footer=localizer.render_with_placeholders(
            footer,
            language=language,
            placeholders=placeholders,
            placeholder_specs=placeholder_specs,
        ),
        style=style,
        ephemeral=ephemeral,
        thumbnail_url=thumbnail_url,
        language=localizer.resolve_language(language),
    )


def build_thread_result(
    localizer: Localizer,
    key: str,
    *,
    thread: ThreadRecord | None,
    style: DiscordResultStyle = DiscordResultStyle.INFO,
    ephemeral: bool = False,
    thumbnail_url: str | None = None,
    **placeholders: object,
) -> DiscordCommandResult:
    """Build one Discord command result using the language configured on a thread."""
    return build_result(
        localizer,
        key,
        language=localizer.language_for_thread(thread),
        style=style,
        ephemeral=ephemeral,
        thumbnail_url=thumbnail_url,
        **placeholders,
    )


def discord_user_mention(localizer: Localizer, user_id: int, *, language: str | None = None) -> str:
    """Build one localized Discord mention string for later placeholder insertion."""
    return f"<@{user_id}>"
