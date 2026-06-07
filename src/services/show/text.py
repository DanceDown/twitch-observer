"""Small helpers that keep `/show` text assembly inside the Localizer."""

from __future__ import annotations

from collections.abc import Mapping

from src.localization import Localizer


def render_section(localizer: Localizer, section_key: str, *, language: str, section_body: str) -> str:
    """Render one full `/show` section from lang-file templates."""
    return localizer.text(
        f"{section_key}.section",
        language=language,
        sources={"view": {"section_body": section_body}},
    )


def render_empty_section(localizer: Localizer, section_key: str, *, language: str) -> str:
    """Render one empty-state section from lang-file templates."""
    return render_section(
        localizer,
        section_key,
        language=language,
        section_body=localizer.text(f"{section_key}.empty", language=language),
    )


def render_rows(localizer: Localizer, section_key: str, *, language: str, items: tuple[object, ...]) -> str:
    """Render one item list using the section-specific lang-file list template."""
    return localizer.text(
        f"{section_key}.rows",
        language=language,
        sources={"view": {"items": items}},
    )


def render_details(localizer: Localizer, section_key: str, *, language: str, items: tuple[str, ...]) -> str:
    """Render one detail list or return an empty suffix when nothing should be shown."""
    if not items:
        return ""
    return localizer.text(
        f"{section_key}.details",
        language=language,
        sources={"view": {"items": items}},
    )


def render_line(localizer: Localizer, section_key: str, *, language: str, view: Mapping[str, object]) -> str:
    """Render one heading/lead line for a section row."""
    return localizer.text(
        f"{section_key}.line",
        language=language,
        sources={"view": dict(view)},
    )


def render_row(localizer: Localizer, section_key: str, *, language: str, view: Mapping[str, object]) -> str:
    """Render one full row from section-specific lang-file templates."""
    return localizer.text(
        f"{section_key}.row",
        language=language,
        sources={"view": dict(view)},
    )
